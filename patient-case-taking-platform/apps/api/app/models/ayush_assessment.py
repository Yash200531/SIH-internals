"""AYUSH (Ayurveda, Yoga & Naturopathy, Unani, Siddha, Homeopathy) assessment models.
Stores evolving assessment envelope; confirmed observations promoted to PostgreSQL."""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import Field

from app.models.base import BaseRecord


class AyushAssessment(BaseRecord):
    """AYUSH clinical assessment linked to an encounter."""
    __tablename__ = "ayush_assessment"

    patient_id: UUID
    encounter_id: UUID
    ayush_system: str  # "ayurveda", "unani", "siddha", "homeopathy", "yoga_naturopathy"

    # Dashavidha Pariksha (Ten-fold examination)
    dashavidha: dict = Field(default_factory=dict)

    # Prakriti (Constitution)
    prakriti: dict = Field(default_factory=dict)

    # Vikriti (Current Imbalance)
    vikriti: dict = Field(default_factory=dict)

    # Agni (Digestive Fire)
    agni: dict = Field(default_factory=dict)

    # Koshtha (Bowel Habits)
    koshtha: dict = Field(default_factory=dict)

    # Ahara-Vihara (Diet and Lifestyle)
    ahara_vihara: dict = Field(default_factory=dict)

    # Nidana (Causative Factors)
    nidana: dict = Field(default_factory=dict)

    # Samprapti (Pathogenesis)
    samprapti: dict = Field(default_factory=dict)

    # Ashtavidha Pariksha (Eight-fold examination)
    ashtavidha: dict = Field(default_factory=dict)

    # Assessment
    clinical_impression: Optional[str] = None
    recommendations: list = Field(default_factory=list)

    # Provenance
    assessed_by: Optional[str] = None
    assessment_date: Optional[datetime] = None
    model_version: Optional[str] = None

    # Lifecycle
    status: str = "draft"  # draft → reviewed → confirmed
    confirmed_by: Optional[str] = None
    confirmed_at: Optional[datetime] = None

    previous_version_id: Optional[UUID] = None
