from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import Field

from app.models.base import BaseRecord


class ConfirmedAnswer(BaseRecord):
    __tablename__ = "confirmed_answer"
    tenant_id: UUID
    encounter_id: UUID
    question_id: str
    question_text: str
    answer_text: str
    answer_data: dict = Field(default_factory=dict)
    source: str = "voice"
    source_utterance_id: Optional[str] = None
    confidence: Optional[float] = None
    confirmed_by: str = "patient"
    confirmed_at: datetime
    version: int = 1
