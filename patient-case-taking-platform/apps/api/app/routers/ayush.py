"""AYUSH assessment and intervention API endpoints."""
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException

from app.schemas.ayush import (
    AyushAssessmentCreate,
    AyushAssessmentResponse,
    AyushInterventionCreate,
    AyushInterventionResponse,
)

router = APIRouter(prefix="/api/v1/ayush", tags=["ayush"])

# In-memory stores (replace with DB in Phase 2)
_assessments: dict[str, dict] = {}
_interventions: dict[str, dict] = {}


@router.post("/assessments", response_model=AyushAssessmentResponse, status_code=201)
async def create_assessment(data: AyushAssessmentCreate):
    """Create a new AYUSH assessment."""
    now = datetime.now(timezone.utc)
    assessment_id = uuid4()
    record = {
        "id": assessment_id,
        "tenant_id": UUID("00000000-0000-0000-0000-000000000001"),
        "patient_id": data.patient_id,
        "encounter_id": data.encounter_id,
        "ayush_system": data.ayush_system,
        "dashavidha": data.dashavidha,
        "prakriti": data.prakriti,
        "vikriti": data.vikriti,
        "agni": data.agni,
        "koshtha": data.koshtha,
        "ahara_vihara": data.ahara_vihara,
        "nidana": data.nidana,
        "samprapti": data.samprapti,
        "ashtavidha": data.ashtavidha,
        "clinical_impression": data.clinical_impression,
        "recommendations": data.recommendations,
        "status": "draft",
        "version": 1,
        "created_at": now,
    }
    _assessments[str(assessment_id)] = record
    return AyushAssessmentResponse.model_validate(record)


@router.get("/assessments/{assessment_id}", response_model=AyushAssessmentResponse)
async def get_assessment(assessment_id: UUID):
    record = _assessments.get(str(assessment_id))
    if not record:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return AyushAssessmentResponse.model_validate(record)


@router.get("/assessments", response_model=list[AyushAssessmentResponse])
async def list_assessments(patient_id: UUID | None = None, encounter_id: UUID | None = None):
    results = list(_assessments.values())
    if patient_id:
        results = [r for r in results if r["patient_id"] == patient_id]
    if encounter_id:
        results = [r for r in results if r["encounter_id"] == encounter_id]
    return [AyushAssessmentResponse.model_validate(record) for record in results]


@router.post("/assessments/{assessment_id}/confirm", response_model=AyushAssessmentResponse)
async def confirm_assessment(assessment_id: UUID):
    """Clinician confirms the assessment."""
    record = _assessments.get(str(assessment_id))
    if not record:
        raise HTTPException(status_code=404, detail="Assessment not found")
    record["status"] = "confirmed"
    record["confirmed_at"] = datetime.now(timezone.utc)
    return AyushAssessmentResponse.model_validate(record)


@router.post("/interventions", response_model=AyushInterventionResponse, status_code=201)
async def create_intervention(data: AyushInterventionCreate):
    now = datetime.now(timezone.utc)
    intervention_id = uuid4()
    record = {
        "id": intervention_id,
        "tenant_id": UUID("00000000-0000-0000-0000-000000000001"),
        "patient_id": data.patient_id,
        "encounter_id": data.encounter_id,
        "intervention_type": data.intervention_type,
        "intervention_name": data.intervention_name,
        "dosage": data.dosage,
        "indicated_for": data.indicated_for,
        "response_status": "prescribed",
        "version": 1,
        "created_at": now,
    }
    _interventions[str(intervention_id)] = record
    return AyushInterventionResponse.model_validate(record)


@router.get("/interventions/{intervention_id}", response_model=AyushInterventionResponse)
async def get_intervention(intervention_id: UUID):
    record = _interventions.get(str(intervention_id))
    if not record:
        raise HTTPException(status_code=404, detail="Intervention not found")
    return AyushInterventionResponse.model_validate(record)


@router.get("/interventions", response_model=list[AyushInterventionResponse])
async def list_interventions(patient_id: UUID | None = None):
    results = list(_interventions.values())
    if patient_id:
        results = [r for r in results if r["patient_id"] == patient_id]
    return [AyushInterventionResponse.model_validate(record) for record in results]
