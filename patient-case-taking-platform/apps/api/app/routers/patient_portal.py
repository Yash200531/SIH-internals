from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response

from app.audit.emitter import audit_emitter
from app.auth.dependencies import get_current_user
from app.auth.token import TokenPayload
from app.config import settings
from app.documents.authorization import ConsentAuthorizationDenied, DocumentPurposeAuthorizer
from app.documents.dependencies import (
    get_document_purpose_authorizer,
    get_document_repository,
    get_document_store,
)
from app.documents.registry import (
    ConcurrentDocumentUpdate,
    DocumentRegistryEntry,
    InvalidDocumentTransition,
)
from app.documents.repository import (
    DocumentNotFound,
    DocumentRepository,
    IdempotencyConflict,
)
from app.documents.storage import (
    DocumentStore,
    ObjectVerificationError,
    quarantine_object_key,
)
from app.patient_portal.consent_repository import (
    PatientConsentNotFound,
    PatientConsentRepository,
)
from app.patient_portal.contracts import (
    PatientConsentCreate,
    PatientConsentResponse,
    PatientDashboardResponse,
    PatientDocumentInitiateRequest,
    PatientIntakeSubmissionCreate,
    PatientIntakeSubmissionResponse,
    PatientReportDetail,
    PatientReportListItem,
)
from app.patient_portal.dependencies import (
    get_patient_consent_repository,
    get_patient_intake_repository,
    get_patient_portal_service,
)
from app.patient_portal.intake_repository import (
    PatientIntakeAuthorizationDenied,
    PatientIntakeConflict,
    PatientIntakeRepository,
)
from app.patient_portal.service import (
    PatientIdentity,
    PatientPortalService,
    PatientReportNotFound,
)
from app.rules.patient_safety import PatientSafetyConfirmation, PatientSafetyService
from app.schemas.document import (
    DocumentFinalizeRequest,
    DocumentResponse,
    DocumentUploadGrantResponse,
    DocumentVersionRequest,
)
from app.schemas.reviewed_document import TimelineEntryResponse

router = APIRouter(prefix="/api/v1/patient-portal/me", tags=["patient-portal"])


def patient_identity(user: TokenPayload = Depends(get_current_user)) -> PatientIdentity:
    if user.role != "patient":
        raise HTTPException(status_code=403, detail="Patient role required")
    try:
        identity = PatientIdentity(
            tenant_id=UUID(user.tenant_id),
            patient_id=UUID(user.user_id),
            facility_ids={UUID(value) for value in user.facility_ids},
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=403, detail="Invalid patient authorization scope") from exc
    if not identity.facility_ids:
        raise HTTPException(status_code=403, detail="Patient facility scope required")
    return identity


@router.get("/dashboard", response_model=PatientDashboardResponse)
async def get_dashboard(
    identity: PatientIdentity = Depends(patient_identity),
    service: PatientPortalService = Depends(get_patient_portal_service),
) -> PatientDashboardResponse:
    return await service.dashboard(identity)


@router.get("/reports", response_model=list[PatientReportListItem])
async def list_reports(
    limit: int = Query(default=100, ge=1, le=200),
    identity: PatientIdentity = Depends(patient_identity),
    service: PatientPortalService = Depends(get_patient_portal_service),
) -> list[PatientReportListItem]:
    return await service.list_reports(identity, limit=limit)


@router.get("/reports/{report_id}", response_model=PatientReportDetail)
async def get_report(
    report_id: UUID,
    identity: PatientIdentity = Depends(patient_identity),
    service: PatientPortalService = Depends(get_patient_portal_service),
) -> PatientReportDetail:
    try:
        return await service.get_report(identity, report_id)
    except PatientReportNotFound as exc:
        raise HTTPException(status_code=404, detail="Patient report not found") from exc


@router.get("/reports/{report_id}/download", response_class=Response)
async def download_report(
    report_id: UUID,
    identity: PatientIdentity = Depends(patient_identity),
    service: PatientPortalService = Depends(get_patient_portal_service),
) -> Response:
    try:
        content = await service.render_report_download(identity, report_id)
    except PatientReportNotFound as exc:
        raise HTTPException(status_code=404, detail="Patient report not found") from exc
    return Response(
        content=content.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f'attachment; filename="medikiosk-report-{report_id}.txt"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/timeline", response_model=list[TimelineEntryResponse])
async def list_timeline(
    limit: int = Query(default=100, ge=1, le=200),
    identity: PatientIdentity = Depends(patient_identity),
    service: PatientPortalService = Depends(get_patient_portal_service),
) -> list[TimelineEntryResponse]:
    return await service.list_timeline(identity, limit=limit)


@router.post("/consents", response_model=PatientConsentResponse, status_code=201)
async def create_consent(
    body: PatientConsentCreate,
    identity: PatientIdentity = Depends(patient_identity),
    repository: PatientConsentRepository = Depends(get_patient_consent_repository),
) -> PatientConsentResponse:
    consent = await repository.create(identity, body)
    audit_emitter.emit(
        tenant_id=identity.tenant_id,
        actor_id=identity.patient_id,
        actor_type="patient",
        actor_role="patient",
        action="patient_consent_grant",
        resource_type="consent",
        resource_id=consent.id,
        purpose="treatment",
        audit_metadata={
            "document_upload": body.document_upload,
            "audio_retention": body.retain_audio,
            "expires_in_hours": body.expires_in_hours,
        },
    )
    return consent


@router.get("/consents", response_model=list[PatientConsentResponse])
async def list_consents(
    limit: int = Query(default=100, ge=1, le=200),
    identity: PatientIdentity = Depends(patient_identity),
    repository: PatientConsentRepository = Depends(get_patient_consent_repository),
) -> list[PatientConsentResponse]:
    return await repository.list_for_patient(identity, limit=limit)


@router.post("/consents/{consent_id}/revoke", response_model=PatientConsentResponse)
async def revoke_consent(
    consent_id: UUID,
    identity: PatientIdentity = Depends(patient_identity),
    repository: PatientConsentRepository = Depends(get_patient_consent_repository),
) -> PatientConsentResponse:
    try:
        consent = await repository.revoke(identity, consent_id)
    except PatientConsentNotFound as exc:
        raise HTTPException(status_code=404, detail="Consent not found") from exc
    audit_emitter.emit(
        tenant_id=identity.tenant_id,
        actor_id=identity.patient_id,
        actor_type="patient",
        actor_role="patient",
        action="patient_consent_revoke",
        resource_type="consent",
        resource_id=consent.id,
        purpose="treatment",
        audit_metadata={"version": consent.version},
    )
    return consent


@router.post("/intakes", response_model=PatientIntakeSubmissionResponse, status_code=201)
async def submit_intake(
    body: PatientIntakeSubmissionCreate,
    idempotency_key: str = Header(
        ..., alias="Idempotency-Key", min_length=1, max_length=128
    ),
    identity: PatientIdentity = Depends(patient_identity),
    repository: PatientIntakeRepository = Depends(get_patient_intake_repository),
) -> PatientIntakeSubmissionResponse:
    try:
        submission = await repository.create(identity, body, idempotency_key)
    except PatientIntakeAuthorizationDenied as exc:
        raise HTTPException(status_code=403, detail="Consent does not authorize this intake") from exc
    except PatientIntakeConflict as exc:
        raise HTTPException(status_code=409, detail="Intake submission conflict") from exc
    audit_emitter.emit(
        tenant_id=identity.tenant_id,
        facility_id=body.facility_id,
        actor_id=identity.patient_id,
        actor_type="patient",
        actor_role="patient",
        action="patient_intake_submit",
        resource_type="encounter",
        resource_id=body.encounter_id,
        purpose="treatment",
        audit_metadata={
            "decision": body.decision,
            "provider": body.provider,
            "confirmed_answer_count": len(body.confirmed_answers),
        },
    )
    return submission


async def _patient_document(
    identity: PatientIdentity,
    document_id: UUID,
    repository: DocumentRepository,
) -> DocumentRegistryEntry:
    try:
        document = await repository.get(identity.tenant_id, document_id)
    except DocumentNotFound as exc:
        raise HTTPException(status_code=404, detail="Document not found") from exc
    if (
        document.patient_id != identity.patient_id
        or document.facility_id not in identity.facility_ids
    ):
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.get("/documents", response_model=list[DocumentResponse])
async def list_documents(
    limit: int = Query(default=100, ge=1, le=200),
    identity: PatientIdentity = Depends(patient_identity),
    repository: DocumentRepository = Depends(get_document_repository),
) -> list[DocumentRegistryEntry]:
    return await repository.list_for_patient(
        tenant_id=identity.tenant_id,
        patient_id=identity.patient_id,
        facility_ids=identity.facility_ids,
        limit=limit,
    )


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    identity: PatientIdentity = Depends(patient_identity),
    repository: DocumentRepository = Depends(get_document_repository),
) -> DocumentRegistryEntry:
    return await _patient_document(identity, document_id, repository)


@router.post("/documents", response_model=DocumentResponse)
async def initiate_document(
    body: PatientDocumentInitiateRequest,
    response: Response,
    idempotency_key: str = Header(
        ..., alias="Idempotency-Key", min_length=1, max_length=128
    ),
    identity: PatientIdentity = Depends(patient_identity),
    repository: DocumentRepository = Depends(get_document_repository),
    authorizer: DocumentPurposeAuthorizer = Depends(get_document_purpose_authorizer),
) -> DocumentRegistryEntry:
    if body.facility_id not in identity.facility_ids:
        raise HTTPException(status_code=403, detail="Facility access denied")
    allowed_mime: set[str] = {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/webp",
    }
    if body.declared_mime not in allowed_mime:
        raise HTTPException(status_code=422, detail="Unsupported prescription file type")
    try:
        await authorizer.authorize(
            tenant_id=identity.tenant_id,
            patient_id=identity.patient_id,
            encounter_id=body.encounter_id,
            purpose="treatment",
            consent_reference=body.consent_reference,
        )
    except ConsentAuthorizationDenied as exc:
        raise HTTPException(
            status_code=403, detail="Active consent does not authorize this upload"
        ) from exc
    document = DocumentRegistryEntry(
        tenant_id=identity.tenant_id,
        facility_id=body.facility_id,
        patient_id=identity.patient_id,
        encounter_id=body.encounter_id,
        uploader_actor_id=identity.patient_id,
        purpose="treatment",
        consent_reference=body.consent_reference,
        original_filename=body.original_filename,
        declared_document_class="prescription",
        declared_mime=body.declared_mime,
        declared_size_bytes=body.declared_size_bytes,
        idempotency_key=idempotency_key,
        upload_expires_at=datetime.now(UTC)
        + timedelta(seconds=settings.DOCUMENT_UPLOAD_SESSION_TTL_SECONDS),
    )
    try:
        result = await repository.create(document)
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail="Idempotency key conflict") from exc
    response.status_code = 201 if result.created else 200
    audit_emitter.emit(
        tenant_id=identity.tenant_id,
        facility_id=body.facility_id,
        actor_id=identity.patient_id,
        actor_type="patient",
        actor_role="patient",
        action="patient_document_register" if result.created else "patient_document_register_replay",
        resource_type="document",
        resource_id=result.document.id,
        purpose="treatment",
        audit_metadata={"state": result.document.state.value},
    )
    return result.document


@router.post(
    "/documents/{document_id}/upload-session",
    response_model=DocumentUploadGrantResponse,
)
async def create_document_upload_session(
    document_id: UUID,
    identity: PatientIdentity = Depends(patient_identity),
    repository: DocumentRepository = Depends(get_document_repository),
    store: DocumentStore = Depends(get_document_store),
) -> DocumentUploadGrantResponse:
    document = await _patient_document(identity, document_id, repository)
    try:
        grant = await store.create_upload_grant(document)
    except ObjectVerificationError as exc:
        raise HTTPException(status_code=409, detail="Document cannot receive an upload grant") from exc
    return DocumentUploadGrantResponse(
        url=grant.url,
        expires_in_seconds=grant.expires_in_seconds,
        required_headers=grant.required_headers,
    )


@router.post("/documents/{document_id}/finalize", response_model=DocumentResponse)
async def finalize_document(
    document_id: UUID,
    body: DocumentFinalizeRequest,
    identity: PatientIdentity = Depends(patient_identity),
    repository: DocumentRepository = Depends(get_document_repository),
    store: DocumentStore = Depends(get_document_store),
) -> DocumentRegistryEntry:
    document = await _patient_document(identity, document_id, repository)
    try:
        verified = await store.verify_upload(document, quarantine_object_key(document))
        finalized = await repository.finalize_upload(
            tenant_id=identity.tenant_id,
            document_id=document.id,
            expected_version=body.expected_version,
            object_key=verified.object_key,
            checksum_sha256=verified.checksum_sha256,
            detected_mime=verified.detected_mime,
        )
    except ObjectVerificationError as exc:
        raise HTTPException(status_code=422, detail="Uploaded object verification failed") from exc
    except (ConcurrentDocumentUpdate, InvalidDocumentTransition) as exc:
        raise HTTPException(status_code=409, detail="Document state conflict") from exc
    audit_emitter.emit(
        tenant_id=identity.tenant_id,
        facility_id=finalized.facility_id,
        actor_id=identity.patient_id,
        actor_type="patient",
        actor_role="patient",
        action="patient_document_finalize",
        resource_type="document",
        resource_id=finalized.id,
        purpose="treatment",
        audit_metadata={"state": finalized.state.value, "version": finalized.version},
    )
    return finalized


@router.post("/documents/{document_id}/cancel", response_model=DocumentResponse)
async def cancel_document(
    document_id: UUID,
    body: DocumentVersionRequest,
    identity: PatientIdentity = Depends(patient_identity),
    repository: DocumentRepository = Depends(get_document_repository),
) -> DocumentRegistryEntry:
    document = await _patient_document(identity, document_id, repository)
    try:
        return await repository.cancel(
            tenant_id=identity.tenant_id,
            document_id=document.id,
            expected_version=body.expected_version,
        )
    except (ConcurrentDocumentUpdate, InvalidDocumentTransition) as exc:
        raise HTTPException(status_code=409, detail="Document state conflict") from exc


async def get_patient_safety_service():
    from app.database import get_postgres_pool
    if not settings.TRIAGE_WORKFLOW_ENABLED or not settings.ENABLE_DEMO_ROUTES:
        raise HTTPException(503, "Prototype patient safety workflow is not enabled")
    return PatientSafetyService(await get_postgres_pool())


@router.post("/safety-confirmations")
async def confirm_patient_safety(
    body: PatientSafetyConfirmation,
    response: Response,
    identity: PatientIdentity = Depends(patient_identity),
    service: PatientSafetyService = Depends(get_patient_safety_service),
):
    response.headers["Cache-Control"] = "private, no-store"
    return await service.confirm(identity, body)
