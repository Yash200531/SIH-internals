"""AYUSH intervention history and response tracking."""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import Field

from app.models.base import BaseRecord


class AyushIntervention(BaseRecord):
    """AYUSH treatment/intervention record linked to a patient."""
    __tablename__ = "ayush_intervention"

    patient_id: UUID
    encounter_id: Optional[UUID] = None

    # Intervention details
    intervention_type: str  # "herbal", "panchakarma", "dietary", "lifestyle", "yoga", "homeopathic"
    intervention_name: str
    dosage: dict = Field(default_factory=dict)

    # Clinical context
    indicated_for: dict = Field(default_factory=dict)
    contraindications_checked: dict = Field(default_factory=dict)

    # Response tracking
    response_status: str = "prescribed"  # prescribed → ongoing → completed → discontinued
    response_notes: Optional[str] = None
    side_effects: list = Field(default_factory=list)

    # Provenance
    prescribed_by: Optional[str] = None
    prescribed_at: Optional[datetime] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
