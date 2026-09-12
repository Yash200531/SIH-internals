from fastapi import HTTPException

from app.config import settings
from app.database import get_postgres_pool
from app.documents.dependencies import get_reviewed_fact_repository
from app.patient_portal.consent_repository import (
    PatientConsentRepository,
    PostgresPatientConsentRepository,
)
from app.patient_portal.intake_repository import (
    PatientIntakeRepository,
    PostgresPatientIntakeRepository,
)
from app.patient_portal.service import PatientPortalService
from app.summary_workflow.dependencies import get_summary_repository


async def get_patient_portal_service() -> PatientPortalService:
    return PatientPortalService(
        await get_summary_repository(),
        await get_reviewed_fact_repository(),
    )


async def get_patient_consent_repository() -> PatientConsentRepository:
    if not settings.DOCUMENT_WORKFLOW_ENABLED:
        raise HTTPException(status_code=503, detail="Patient consent workflow is not enabled")
    return PostgresPatientConsentRepository(await get_postgres_pool())


async def get_patient_intake_repository() -> PatientIntakeRepository:
    if not settings.DOCUMENT_WORKFLOW_ENABLED:
        raise HTTPException(status_code=503, detail="Patient intake workflow is not enabled")
    return PostgresPatientIntakeRepository(await get_postgres_pool())
