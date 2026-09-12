"""FHIR R4 export endpoints for ABDM exchange."""
from fastapi import APIRouter

from app.fhir.mappings import fhir_mapper

router = APIRouter(prefix="/api/v1/fhir", tags=["fhir"])


@router.get("/patient/{patient_id}")
async def get_patient_fhir(patient_id: str):
    """Export patient as FHIR Patient resource."""
    return fhir_mapper.patient_to_fhir({
        "id": patient_id,
        "full_name": "Placeholder Patient",
        "gender": "unknown",
        "is_active": True
    })


@router.get("/encounter/{encounter_id}")
async def get_encounter_fhir(encounter_id: str):
    """Export encounter as FHIR Encounter resource."""
    return fhir_mapper.encounter_to_fhir({
        "id": encounter_id,
        "patient_id": "00000000-0000-0000-0000-000000000000",
        "status": "signed"
    })


@router.get("/encounter/{encounter_id}/composition")
async def get_encounter_composition(encounter_id: str):
    """Export encounter as FHIR Composition (clinical summary)."""
    return fhir_mapper.clinical_summary_to_fhir_composition({
        "id": encounter_id,
        "patient_id": "00000000-0000-0000-0000-000000000000",
        "encounter_id": encounter_id,
        "summary_type": "encounter",
        "status": "signed",
        "raw_text": "Placeholder clinical summary",
        "created_at": "2026-08-29T00:00:00Z",
        "signed_by": "00000000-0000-0000-0000-000000000000"
    })
