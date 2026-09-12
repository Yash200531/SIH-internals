from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class AyushAssessmentCreate(BaseModel):
    patient_id: UUID
    encounter_id: UUID
    ayush_system: str
    dashavidha: dict = {}
    prakriti: dict = {}
    vikriti: dict = {}
    agni: dict = {}
    koshtha: dict = {}
    ahara_vihara: dict = {}
    nidana: dict = {}
    samprapti: dict = {}
    ashtavidha: dict = {}
    clinical_impression: Optional[str] = None
    recommendations: list[dict] = []


class AyushAssessmentResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    patient_id: UUID
    encounter_id: UUID
    ayush_system: str
    status: str
    version: int
    created_at: datetime


class AyushInterventionCreate(BaseModel):
    patient_id: UUID
    encounter_id: Optional[UUID] = None
    intervention_type: str
    intervention_name: str
    dosage: dict = {}
    indicated_for: dict = {}


class AyushInterventionResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    patient_id: UUID
    intervention_type: str
    intervention_name: str
    response_status: str
    version: int
    created_at: datetime
