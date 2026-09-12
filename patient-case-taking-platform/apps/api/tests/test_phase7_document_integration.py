"""Live PostgreSQL and MinIO integration tests for Phase 7 document ingestion."""

import asyncio
import json
import os
from datetime import UTC, datetime
from io import BytesIO
from typing import AsyncIterator
from uuid import uuid4

import asyncpg
import boto3
import httpx
import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from PIL import Image

from app.documents.authorization import (
    ConsentAuthorizationDenied,
    PostgresDocumentPurposeAuthorizer,
)
from app.documents.cleanup import PostgresAbandonedUploadCleaner
from app.documents.normalization import DocumentNormalizer
from app.documents.normalization_repository import (
    PostgresDocumentNormalizationRepository,
)
from app.documents.normalization_service import DocumentNormalizationService
from app.documents.ocr_artifact_store import MongoOcrArtifactStore
from app.documents.ocr_repository import PostgresDocumentOcrRepository
from app.documents.ocr_service import DocumentOcrService
from app.documents.operations import PostgresDocumentOperationsRepository
from app.documents.promotion import PostgresReviewedFactRepository
from app.documents.registry import DocumentRegistryEntry, DocumentState
from app.documents.repository import DocumentNotFound, PostgresDocumentRepository
from app.documents.review import ManualCandidate
from app.documents.review_repository import PostgresDocumentReviewRepository
from app.documents.scan_repository import PostgresDocumentScanRepository
from app.documents.scan_service import DocumentScanService
from app.documents.scanning import ClamAVScanner, MalwareScanOutcome
from app.documents.storage import S3DocumentStore
from app.migrations import apply_migrations
from app.ocr.mock_provider import MockOCRProvider
from app.search.contracts import SourceKind
from app.search.projection import PostgresClinicalProjectionRepository

pytestmark = pytest.mark.skipif(
    os.getenv("PHASE7_INTEGRATION") != "1",
    reason="set PHASE7_INTEGRATION=1 when local PostgreSQL and MinIO are running",
)

DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://notmid:notmid-local-only@localhost:5432/notmid",
)
def _document() -> DocumentRegistryEntry:
    return DocumentRegistryEntry(
        tenant_id=uuid4(),
        facility_id=uuid4(),
        patient_id=uuid4(),
        encounter_id=uuid4(),
        uploader_actor_id=uuid4(),
        purpose="treatment",
        consent_reference="consent/synthetic-version-1",
        original_filename="synthetic-prescription.jpg",
        declared_document_class="prescription",
        declared_mime="image/jpeg",
        declared_size_bytes=16,
        idempotency_key="integration-upload-1",
    )


@pytest.mark.asyncio
async def test_migration_runner_applies_once_in_an_isolated_schema() -> None:
    schema = f"phase7_runner_{uuid4().hex}"
    connection = await asyncpg.connect(DATABASE_URL)
    try:
        await connection.execute(f'CREATE SCHEMA "{schema}"')
        await connection.execute(f'SET search_path TO "{schema}"')

        first_count = await apply_migrations(connection)
        second_count = await apply_migrations(connection)
        tables = await connection.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = $1",
            schema,
        )

        assert first_count == 19
        assert second_count == 0
        assert {row["tablename"] for row in tables} == {
            "document_registry",
            "document_outbox",
            "consent_artifact",
            "document_scan_run",
            "document_normalization_run",
            "document_page_artifact",
            "document_ocr_run",
            "document_ocr_page_ref",
            "document_extraction_run",
            "document_extraction_candidate",
            "document_review_decision",
            "document_promotion_receipt",
            "reviewed_document_fact",
            "document_fact_status_history",
            "clinical_timeline_projection",
            "document_fhir_projection",
            "document_search_projection",
            "confirmed_encounter_summary_context",
            "clinical_summary_workflow",
            "clinical_summary_action",
            "clinical_summary_outbox",
            "patient_intake_submission",
            "clinical_search_audit",
            "schema_migration",
            "triage_flag", "triage_flag_history", "triage_outbox",
            "triage_policy_artifact", "triage_active_policy", "triage_policy_activation_history",
            "auth_identity_binding", "auth_identity_history", "auth_revoked_session",
        }
    finally:
        await connection.execute("SET search_path TO public")
        await connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await connection.close()


@pytest_asyncio.fixture
async def postgres_repository() -> AsyncIterator[
    tuple[PostgresDocumentRepository, str, asyncpg.Pool]
]:
    suffix = uuid4().hex
    schema = f"phase7_{suffix}"
    role = f"phase7_role_{suffix}"
    admin = await asyncpg.connect(DATABASE_URL)
    pool = None
    try:
        await admin.execute(f'CREATE SCHEMA "{schema}"')
        await admin.execute(f'SET search_path TO "{schema}"')
        await apply_migrations(admin)
        await admin.execute(f'CREATE ROLE "{role}" NOLOGIN NOSUPERUSER NOBYPASSRLS')
        await admin.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"')
        await admin.execute(f'GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA "{schema}" TO "{role}"')
        await admin.execute(
            f'''GRANT DELETE ON
                "{schema}".clinical_timeline_projection,
                "{schema}".document_fhir_projection,
                "{schema}".document_search_projection TO "{role}"'''
        )

        async def initialize(connection: asyncpg.Connection) -> None:
            await connection.execute(f'SET ROLE "{role}"')
            await connection.execute(f'SET search_path TO "{schema}"')

        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2, setup=initialize)
        assert pool is not None
        yield PostgresDocumentRepository(pool), schema, pool
    finally:
        if pool is not None:
            await pool.close()
        await admin.execute("RESET ROLE")
        await admin.execute("SET search_path TO public")
        await admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await admin.execute(f'DROP ROLE IF EXISTS "{role}"')
        await admin.close()


@pytest.mark.asyncio
async def test_postgres_repository_enforces_rls_and_idempotent_registration(
    postgres_repository: tuple[PostgresDocumentRepository, str, asyncpg.Pool],
) -> None:
    repository, _schema, _pool = postgres_repository
    document = _document()

    created = await repository.create(document)
    replay = await repository.create(document.model_copy(update={"id": uuid4()}))

    assert created.created is True
    assert replay.created is False
    assert replay.document.id == document.id
    with pytest.raises(DocumentNotFound):
        await repository.get(uuid4(), document.id)


@pytest.mark.asyncio
async def test_postgres_consent_authorization_is_active_and_tenant_scoped() -> None:
    suffix = uuid4().hex
    schema = f"phase7_consent_{suffix}"
    role = f"phase7_consent_role_{suffix}"
    tenant_id = uuid4()
    patient_id = uuid4()
    encounter_id = uuid4()
    consent_id = uuid4()
    admin = await asyncpg.connect(DATABASE_URL)
    pool = None
    try:
        await admin.execute(f'CREATE SCHEMA "{schema}"')
        await admin.execute(f'SET search_path TO "{schema}"')
        await apply_migrations(admin)
        await admin.execute(
            """
            INSERT INTO consent_artifact (
                id, tenant_id, patient_id, encounter_id, purpose, scope, status
            ) VALUES ($1, $2, $3, $4, 'treatment', '{"document_upload": true}', 'granted')
            """,
            consent_id,
            tenant_id,
            patient_id,
            encounter_id,
        )
        await admin.execute(f'CREATE ROLE "{role}" NOLOGIN NOSUPERUSER NOBYPASSRLS')
        await admin.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"')
        await admin.execute(f'GRANT SELECT ON consent_artifact TO "{role}"')

        async def initialize(connection: asyncpg.Connection) -> None:
            await connection.execute(f'SET ROLE "{role}"')
            await connection.execute(f'SET search_path TO "{schema}"')

        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2, setup=initialize)
        authorizer = PostgresDocumentPurposeAuthorizer(pool)
        scope = {
            "tenant_id": tenant_id,
            "patient_id": patient_id,
            "encounter_id": encounter_id,
            "purpose": "treatment",
            "consent_reference": str(consent_id),
        }

        await authorizer.authorize(**scope)
        with pytest.raises(ConsentAuthorizationDenied):
            await authorizer.authorize(**(scope | {"tenant_id": uuid4()}))
    finally:
        if pool is not None:
            await pool.close()
        await admin.execute("RESET ROLE")
        await admin.execute("SET search_path TO public")
        await admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await admin.execute(f'DROP ROLE IF EXISTS "{role}"')
        await admin.close()


@pytest.mark.asyncio
async def test_abandoned_upload_cleanup_is_durable_and_emits_safe_event() -> None:
    schema = f"phase7_cleanup_{uuid4().hex}"
    document = _document()
    admin = await asyncpg.connect(DATABASE_URL)
    pool = None
    try:
        await admin.execute(f'CREATE SCHEMA "{schema}"')
        await admin.execute(f'SET search_path TO "{schema}"')
        await apply_migrations(admin)
        await admin.execute(
            """
            INSERT INTO document_registry (
                id, tenant_id, facility_id, patient_id, encounter_id,
                uploader_actor_id, purpose, consent_reference, original_filename,
                declared_mime, declared_size_bytes, idempotency_key,
                upload_expires_at, state, version, created_at, updated_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                CURRENT_TIMESTAMP - INTERVAL '1 minute', 'initiated', 1,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """,
            document.id,
            document.tenant_id,
            document.facility_id,
            document.patient_id,
            document.encounter_id,
            document.uploader_actor_id,
            document.purpose,
            document.consent_reference,
            document.original_filename,
            document.declared_mime,
            document.declared_size_bytes,
            document.idempotency_key,
        )

        async def initialize(connection: asyncpg.Connection) -> None:
            await connection.execute(f'SET search_path TO "{schema}"')

        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2, setup=initialize)
        expired = await PostgresAbandonedUploadCleaner(pool).expire(
            now=datetime.now(UTC),
            limit=10,
        )

        assert [item.document_id for item in expired] == [document.id]
        row = await admin.fetchrow(
            "SELECT state, version FROM document_registry WHERE id = $1", document.id
        )
        event = await admin.fetchrow(
            "SELECT event_type, payload FROM document_outbox WHERE aggregate_id = $1",
            document.id,
        )
        assert row is not None and dict(row) == {"state": "cancelled", "version": 2}
        assert event is not None and event["event_type"] == "DocumentUploadExpired.v1"
        assert str(document.patient_id) not in str(dict(event))
    finally:
        if pool is not None:
            await pool.close()
        await admin.execute("SET search_path TO public")
        await admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await admin.close()


@pytest.mark.asyncio
async def test_postgres_finalize_commits_quarantine_state_and_safe_outbox(
    postgres_repository: tuple[PostgresDocumentRepository, str, asyncpg.Pool],
) -> None:
    repository, schema, _pool = postgres_repository
    document = _document()
    await repository.create(document)
    object_key = f"quarantine/{document.tenant_id}/{document.id}/source"

    finalized = await repository.finalize_upload(
        tenant_id=document.tenant_id,
        document_id=document.id,
        expected_version=1,
        object_key=object_key,
        checksum_sha256="a" * 64,
        detected_mime="image/jpeg",
    )

    assert finalized.state is DocumentState.QUARANTINED
    assert finalized.version == 3
    admin = await asyncpg.connect(DATABASE_URL)
    try:
        row = await admin.fetchrow(f'SELECT * FROM "{schema}".document_outbox')
    finally:
        await admin.close()
    assert row is not None
    assert row["event_type"] == "DocumentUploaded.v1"
    serialized = json.dumps(dict(row), default=str)
    assert document.original_filename not in serialized
    assert str(document.patient_id) not in serialized


@pytest.mark.asyncio
async def test_minio_presigned_upload_is_verified_from_stored_bytes() -> None:
    endpoint = os.getenv("TEST_S3_ENDPOINT", "http://127.0.0.1:9000")
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.getenv("TEST_S3_ACCESS_KEY", "notmid-local"),
        aws_secret_access_key=os.getenv(
            "TEST_S3_SECRET_KEY", "notmid-local-only-change-me"
        ),
        region_name="us-east-1",
    )
    bucket = f"phase7-{uuid4().hex}"
    await asyncio.to_thread(client.create_bucket, Bucket=bucket)
    data = b"\xff\xd8\xffsynthetic-jpeg"
    document = _document().model_copy(update={"declared_size_bytes": len(data)})
    store = S3DocumentStore(client=client, bucket=bucket, server_side_encryption="")
    try:
        grant = await store.create_upload_grant(document)
        async with httpx.AsyncClient() as http:
            response = await http.put(grant.url, content=data, headers=grant.required_headers)
        assert response.status_code == 200, response.text

        verified = await store.verify_upload(document, grant.object_key)
        assert verified.detected_mime == "image/jpeg"
        assert verified.size_bytes == len(data)
        async with httpx.AsyncClient() as http:
            anonymous = await http.get(f"{endpoint}/{bucket}/{grant.object_key}")
        assert anonymous.status_code == 403
    finally:
        await asyncio.to_thread(
            client.delete_object,
            Bucket=bucket,
            Key=f"quarantine/{document.tenant_id}/{document.id}/source",
        )
        await asyncio.to_thread(client.delete_bucket, Bucket=bucket)


@pytest.mark.asyncio
async def test_clamav_detects_eicar_and_accepts_clean_synthetic_bytes() -> None:
    scanner = ClamAVScanner(
        host=os.getenv("TEST_CLAMAV_HOST", "127.0.0.1"),
        port=int(os.getenv("TEST_CLAMAV_PORT", "3310")),
        timeout_seconds=30,
    )
    eicar = (
        b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!"
        b"$H+H*"
    )

    clean = await scanner.scan(b"MediKiosk synthetic clean fixture")
    infected = await scanner.scan(eicar)

    assert clean.outcome is MalwareScanOutcome.CLEAN
    assert infected.outcome is MalwareScanOutcome.INFECTED
    assert infected.threat_name


@pytest.mark.asyncio
async def test_clean_document_scan_persists_run_and_promotes_private_source(
    postgres_repository: tuple[PostgresDocumentRepository, str, asyncpg.Pool],
) -> None:
    repository, schema, pool = postgres_repository
    endpoint = os.getenv("TEST_S3_ENDPOINT", "http://127.0.0.1:9000")
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.getenv("TEST_S3_ACCESS_KEY", "notmid-local"),
        aws_secret_access_key=os.getenv(
            "TEST_S3_SECRET_KEY", "notmid-local-only-change-me"
        ),
        region_name="us-east-1",
    )
    bucket = f"phase7-scan-{uuid4().hex}"
    await asyncio.to_thread(client.create_bucket, Bucket=bucket)
    data = b"\xff\xd8\xffMediKiosk synthetic clean image"
    document = _document().model_copy(
        update={
            "declared_size_bytes": len(data),
            "idempotency_key": f"scan-{uuid4()}",
        }
    )
    store = S3DocumentStore(client=client, bucket=bucket, server_side_encryption="")
    try:
        await repository.create(document)
        grant = await store.create_upload_grant(document)
        async with httpx.AsyncClient() as http:
            upload = await http.put(grant.url, content=data, headers=grant.required_headers)
        assert upload.status_code == 200
        verified = await store.verify_upload(document, grant.object_key)
        quarantined = await repository.finalize_upload(
            tenant_id=document.tenant_id,
            document_id=document.id,
            expected_version=1,
            object_key=verified.object_key,
            checksum_sha256=verified.checksum_sha256,
            detected_mime=verified.detected_mime,
        )
        scanner = ClamAVScanner(
            host=os.getenv("TEST_CLAMAV_HOST", "127.0.0.1"),
            port=int(os.getenv("TEST_CLAMAV_PORT", "3310")),
            timeout_seconds=30,
        )
        await DocumentScanService(
            PostgresDocumentScanRepository(pool),
            store,
            scanner,
        ).process(
            tenant_id=document.tenant_id,
            document_id=document.id,
            expected_version=quarantined.version,
        )

        completed = await repository.get(document.tenant_id, document.id)
        assert completed.state is DocumentState.SCAN_PASSED
        assert completed.processing_object_key is not None
        head = await asyncio.to_thread(
            client.head_object,
            Bucket=bucket,
            Key=completed.processing_object_key,
        )
        assert head["ContentLength"] == len(data)
        admin = await asyncpg.connect(DATABASE_URL)
        try:
            scan = await admin.fetchrow(
                f'SELECT status, outcome, engine_version FROM "{schema}".document_scan_run'
            )
        finally:
            await admin.close()
        assert scan is not None
        assert dict(scan)["status"] == "completed"
        assert dict(scan)["outcome"] == "clean"
    finally:
        objects = await asyncio.to_thread(client.list_objects_v2, Bucket=bucket)
        for item in objects.get("Contents", []):
            await asyncio.to_thread(client.delete_object, Bucket=bucket, Key=item["Key"])
        await asyncio.to_thread(client.delete_bucket, Bucket=bucket)


@pytest.mark.asyncio
async def test_clean_document_is_normalized_and_ocr_artifact_is_durable(
    postgres_repository: tuple[PostgresDocumentRepository, str, asyncpg.Pool],
) -> None:
    repository, schema, pool = postgres_repository
    endpoint = os.getenv("TEST_S3_ENDPOINT", "http://127.0.0.1:9000")
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.getenv("TEST_S3_ACCESS_KEY", "notmid-local"),
        aws_secret_access_key=os.getenv(
            "TEST_S3_SECRET_KEY", "notmid-local-only-change-me"
        ),
        region_name="us-east-1",
    )
    bucket = f"phase7-normalize-{uuid4().hex}"
    await asyncio.to_thread(client.create_bucket, Bucket=bucket)
    mongo: AsyncIOMotorClient[dict] = AsyncIOMotorClient(
        os.getenv("TEST_MONGODB_URL", "mongodb://127.0.0.1:27017")
    )
    mongo_database = f"phase7_pipeline_{uuid4().hex}"
    artifact_store = MongoOcrArtifactStore(
        mongo[mongo_database]["document_ocr_artifacts"]
    )
    source = BytesIO()
    Image.new("RGB", (8, 6), "white").save(source, format="PNG")
    data = source.getvalue()
    document = _document().model_copy(
        update={
            "declared_mime": "image/png",
            "declared_size_bytes": len(data),
            "idempotency_key": f"normalize-{uuid4()}",
        }
    )
    store = S3DocumentStore(client=client, bucket=bucket, server_side_encryption="")
    try:
        await repository.create(document)
        grant = await store.create_upload_grant(document)
        async with httpx.AsyncClient() as http:
            upload = await http.put(grant.url, content=data, headers=grant.required_headers)
        assert upload.status_code == 200
        verified = await store.verify_upload(document, grant.object_key)
        quarantined = await repository.finalize_upload(
            tenant_id=document.tenant_id,
            document_id=document.id,
            expected_version=1,
            object_key=verified.object_key,
            checksum_sha256=verified.checksum_sha256,
            detected_mime=verified.detected_mime,
        )
        await DocumentScanService(
            PostgresDocumentScanRepository(pool),
            store,
            ClamAVScanner(
                host=os.getenv("TEST_CLAMAV_HOST", "127.0.0.1"),
                port=int(os.getenv("TEST_CLAMAV_PORT", "3310")),
                timeout_seconds=30,
            ),
        ).process(
            tenant_id=document.tenant_id,
            document_id=document.id,
            expected_version=quarantined.version,
        )
        scan_passed = await repository.get(document.tenant_id, document.id)
        await DocumentNormalizationService(
            PostgresDocumentNormalizationRepository(pool),
            store,
            DocumentNormalizer(
                max_pages=20,
                max_pixels_per_page=1_000_000,
                max_total_pixels=1_000_000,
            ),
        ).process(
            tenant_id=document.tenant_id,
            document_id=document.id,
            expected_version=scan_passed.version,
        )

        normalized = await repository.get(document.tenant_id, document.id)
        assert normalized.state is DocumentState.PROCESSING
        assert normalized.version == 7
        admin = await asyncpg.connect(DATABASE_URL)
        try:
            run = await admin.fetchrow(
                f'SELECT status, preprocessing_version FROM "{schema}".document_normalization_run'
            )
            page = await admin.fetchrow(
                f'SELECT * FROM "{schema}".document_page_artifact'
            )
            event = await admin.fetchrow(
                f'''SELECT artifact_refs, payload FROM "{schema}".document_outbox
                    WHERE event_type = 'DocumentPagesNormalized.v1' '''
            )
        finally:
            await admin.close()
        assert run is not None and dict(run) == {
            "status": "completed",
            "preprocessing_version": "normalize.v1",
        }
        assert page is not None
        assert page["page_number"] == 1
        assert page["width"] == 8
        assert page["height"] == 6
        stored = await asyncio.to_thread(
            client.get_object,
            Bucket=bucket,
            Key=page["object_key"],
        )
        body = stored["Body"]
        try:
            normalized_bytes = await asyncio.to_thread(body.read)
        finally:
            body.close()
        assert normalized_bytes.startswith(b"\x89PNG\r\n\x1a\n")
        assert event is not None
        serialized = json.dumps(dict(event), default=str)
        assert document.original_filename not in serialized
        assert str(document.patient_id) not in serialized

        await artifact_store.ensure_indexes()
        await DocumentOcrService(
            PostgresDocumentOcrRepository(pool),
            store,
            artifact_store,
            MockOCRProvider(),
        ).process(
            tenant_id=document.tenant_id,
            document_id=document.id,
            expected_version=normalized.version,
        )
        ocr_completed = await repository.get(document.tenant_id, document.id)
        assert ocr_completed.state is DocumentState.PROCESSING
        assert ocr_completed.version == 9
        admin = await asyncpg.connect(DATABASE_URL)
        try:
            ocr_run = await admin.fetchrow(
                f'SELECT status, provider, model_version FROM "{schema}".document_ocr_run'
            )
            ocr_ref = await admin.fetchrow(
                f'SELECT artifact_id, page_artifact_id FROM "{schema}".document_ocr_page_ref'
            )
            ocr_event = await admin.fetchrow(
                f'''SELECT artifact_refs, payload FROM "{schema}".document_outbox
                    WHERE event_type = 'ai.ocr.completed.v1' '''
            )
        finally:
            await admin.close()
        assert ocr_run is not None and dict(ocr_run) == {
            "status": "completed",
            "provider": "mock",
            "model_version": "mock-ocr-v1",
        }
        assert ocr_ref is not None
        artifact = await artifact_store.get(
            document.tenant_id,
            ocr_ref["artifact_id"],
        )
        assert artifact is not None
        assert artifact.page_artifact_id == ocr_ref["page_artifact_id"]
        assert artifact.source_checksum_sha256 == verified.checksum_sha256
        assert artifact.review_required is True
        assert ocr_event is not None
        ocr_serialized = json.dumps(dict(ocr_event), default=str)
        assert artifact.normalized_text not in ocr_serialized
        assert document.original_filename not in ocr_serialized
        assert str(document.patient_id) not in ocr_serialized

        reviewer_id = uuid4()
        review_repository = PostgresDocumentReviewRepository(pool)
        opened = await review_repository.open_manual_review(
            tenant_id=document.tenant_id,
            document_id=document.id,
            facility_ids={document.facility_id},
            actor_id=reviewer_id,
            actor_role="doctor",
            expected_document_version=ocr_completed.version,
            idempotency_key=f"manual-review-{document.id}",
        )
        assert opened.state == "review_required"
        assert opened.candidates == ()
        assert len(opened.pages) == 1
        queued = await review_repository.list_queue(
            tenant_id=document.tenant_id,
            facility_ids={document.facility_id},
        )
        assert [item.document_id for item in queued] == [document.id]
        detail = await review_repository.get(
            tenant_id=document.tenant_id,
            document_id=document.id,
        )
        assert detail.pages == opened.pages
        page_detail = await review_repository.get_page(
            tenant_id=document.tenant_id,
            document_id=document.id,
            page_artifact_id=opened.pages[0].id,
        )
        assert page_detail.page_number == 1

        manual = await review_repository.add_manual_candidate(
            tenant_id=document.tenant_id,
            document_id=document.id,
            facility_ids={document.facility_id},
            actor_id=reviewer_id,
            actor_role="doctor",
            idempotency_key=f"manual-candidate-{document.id}",
            candidate=ManualCandidate(
                entity_type="medication_statement",
                normalized_value="Synthetic medicine",
                unit=None,
                source_page_artifact_id=opened.pages[0].id,
                source_page_number=opened.pages[0].page_number,
                source_verified=True,
            ),
        )
        assert manual.review_state.value == "corrected"

        finalized = await review_repository.finalize(
            tenant_id=document.tenant_id,
            document_id=document.id,
            facility_ids={document.facility_id},
            actor_id=reviewer_id,
            actor_role="doctor",
            expected_document_version=opened.version,
            idempotency_key=f"finalize-{document.id}",
        )
        assert finalized.state == "reviewed"

        admin = await asyncpg.connect(DATABASE_URL)
        try:
            completion_event_id = await admin.fetchval(
                f'''SELECT event_id FROM "{schema}".document_outbox
                    WHERE aggregate_id = $1
                      AND event_type = 'DocumentReviewCompleted.v1' ''',
                document.id,
            )
        finally:
            await admin.close()
        assert completion_event_id is not None

        promoted = await PostgresReviewedFactRepository(pool).promote(
            tenant_id=document.tenant_id,
            document_id=document.id,
            source_event_id=completion_event_id,
            actor_id=reviewer_id,
            actor_role="doctor",
        )
        assert promoted.promoted_fact_count == 1
        assert promoted.replayed is False

        fact_repository = PostgresReviewedFactRepository(pool)
        facts = await fact_repository.list_facts(
            tenant_id=document.tenant_id,
            document_id=document.id,
            facility_ids={document.facility_id},
        )
        timeline = await fact_repository.list_timeline(
            tenant_id=document.tenant_id,
            patient_id=document.patient_id,
            facility_ids={document.facility_id},
        )
        timeline_total = await fact_repository.count_timeline(
            tenant_id=document.tenant_id,
            patient_id=document.patient_id,
            facility_ids={document.facility_id},
        )
        fhir_resources = await fact_repository.list_fhir_resources(
            tenant_id=document.tenant_id,
            document_id=document.id,
            facility_ids={document.facility_id},
        )
        assert len(facts) == len(timeline) == timeline_total == len(fhir_resources) == 1
        assert facts[0].normalized_value == "Synthetic medicine"
        assert timeline[0].statement_status == "document_stated"
        assert fhir_resources[0]["resourceType"] == "Basic"
        search_records = await PostgresClinicalProjectionRepository(
            pool
        ).list_patient_records(
            tenant_id=document.tenant_id,
            patient_id=document.patient_id,
            facility_ids={document.facility_id},
            source_kind=SourceKind.REVIEWED_FACT,
        )
        assert [record.source_id for record in search_records] == [facts[0].id]
        assert search_records[0].document_id == document.id
        operations = await PostgresDocumentOperationsRepository(pool).snapshot(
            document.tenant_id
        )
        assert operations.review_backlog == 0
        assert operations.projection_reconciliation_issues == 0

        admin = await asyncpg.connect(DATABASE_URL)
        try:
            fact_count = await admin.fetchval(
                f'SELECT COUNT(*) FROM "{schema}".reviewed_document_fact'
            )
            timeline_count = await admin.fetchval(
                f'SELECT COUNT(*) FROM "{schema}".clinical_timeline_projection'
            )
            fhir_count = await admin.fetchval(
                f'SELECT COUNT(*) FROM "{schema}".document_fhir_projection'
            )
            search_count = await admin.fetchval(
                f'SELECT COUNT(*) FROM "{schema}".document_search_projection'
            )
        finally:
            await admin.close()
        assert (fact_count, timeline_count, fhir_count, search_count) == (1, 1, 1, 1)
    finally:
        await mongo.drop_database(mongo_database)
        mongo.close()
        objects = await asyncio.to_thread(client.list_objects_v2, Bucket=bucket)
        for item in objects.get("Contents", []):
            await asyncio.to_thread(client.delete_object, Bucket=bucket, Key=item["Key"])
        await asyncio.to_thread(client.delete_bucket, Bucket=bucket)
