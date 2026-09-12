"""Clinical document review contracts and validation rules."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class ReviewAction(StrEnum):
    ACCEPT = "accept"
    CORRECT = "correct"
    REJECT = "reject"
    UNREADABLE = "unreadable"
    REQUEST_RESCAN = "request_rescan"
    DEFER = "defer"
    MANUAL_ENTRY = "manual_entry"


class ReviewState(StrEnum):
    UNREVIEWED = "unreviewed"
    ACCEPTED = "accepted"
    CORRECTED = "corrected"
    REJECTED = "rejected"
    UNREADABLE = "unreadable"
    RESCAN_REQUESTED = "rescan_requested"
    DEFERRED = "deferred"


_ACTION_STATE = {
    ReviewAction.ACCEPT: ReviewState.ACCEPTED,
    ReviewAction.CORRECT: ReviewState.CORRECTED,
    ReviewAction.REJECT: ReviewState.REJECTED,
    ReviewAction.UNREADABLE: ReviewState.UNREADABLE,
    ReviewAction.REQUEST_RESCAN: ReviewState.RESCAN_REQUESTED,
    ReviewAction.DEFER: ReviewState.DEFERRED,
    ReviewAction.MANUAL_ENTRY: ReviewState.CORRECTED,
}


class ReviewConflict(ValueError):
    """Raised when a review mutation is stale or idempotently inconsistent."""


class ReviewIncomplete(ValueError):
    """Raised when finalization is attempted with unresolved candidates."""


@dataclass(frozen=True)
class ReviewQueueItem:
    document_id: UUID
    facility_id: UUID
    patient_id: UUID
    encounter_id: UUID
    document_class: str
    state: str
    version: int
    updated_at: datetime
    candidate_count: int
    unresolved_count: int


@dataclass(frozen=True)
class ReviewCandidate:
    candidate_id: UUID
    entity_type: str
    normalized_value: str | None
    unit: str | None
    source_page_artifact_id: UUID
    source_ocr_artifact_id: UUID | None
    source_region_id: UUID | None
    source_page_number: int
    parser_signal: str
    negated: bool
    temporality: str
    subject: str
    uncertainty: str | None
    document_statement: bool
    clinician_confirmed_current: bool
    review_state: ReviewState
    version: int
    source_page_width: int | None = None
    source_page_height: int | None = None
    source_bbox: tuple[int, int, int, int] | None = None
    source_polygon: tuple[tuple[int, int], ...] | None = None


@dataclass(frozen=True)
class ReviewPage:
    id: UUID
    page_number: int
    width: int
    height: int
    preprocessing_version: str


@dataclass(frozen=True)
class ReviewDocument:
    document_id: UUID
    tenant_id: UUID
    facility_id: UUID
    patient_id: UUID
    encounter_id: UUID
    purpose: str
    document_class: str
    state: str
    version: int
    updated_at: datetime
    candidates: tuple[ReviewCandidate, ...]
    pages: tuple[ReviewPage, ...] = ()


@dataclass(frozen=True)
class CandidateDecision:
    action: ReviewAction
    expected_candidate_version: int
    corrected_value: str | None = None
    corrected_unit: str | None = None
    reason_code: str | None = None
    source_verified: bool = False

    def validate(self) -> ReviewState:
        if self.expected_candidate_version <= 0:
            raise ValueError("Candidate version must be positive")
        if self.action in {ReviewAction.CORRECT, ReviewAction.MANUAL_ENTRY}:
            if not self.corrected_value or not self.corrected_value.strip():
                raise ValueError("A corrected value is required")
        elif self.corrected_value is not None or self.corrected_unit is not None:
            raise ValueError("Corrections are only valid for the correct action")
        if self.action in {
            ReviewAction.REJECT,
            ReviewAction.UNREADABLE,
            ReviewAction.REQUEST_RESCAN,
        } and not self.reason_code:
            raise ValueError("This review action requires a reason code")
        if self.action in {
            ReviewAction.ACCEPT,
            ReviewAction.CORRECT,
            ReviewAction.MANUAL_ENTRY,
        } and not self.source_verified:
            raise ValueError("Source verification is required before acceptance")
        return _ACTION_STATE[self.action]


@dataclass(frozen=True)
class ManualCandidate:
    entity_type: str
    normalized_value: str
    unit: str | None
    source_page_artifact_id: UUID
    source_page_number: int
    source_verified: bool

    def validate(self) -> None:
        supported = {
            "document_date",
            "medication_statement",
            "strength",
            "route",
            "frequency",
            "duration",
            "instructions",
        }
        if self.entity_type not in supported:
            raise ValueError("Manual candidate type is unsupported")
        if not self.normalized_value.strip() or len(self.normalized_value) > 2_000:
            raise ValueError("Manual candidate value is invalid")
        if self.unit is not None and len(self.unit) > 32:
            raise ValueError("Manual candidate unit is invalid")
        if self.source_page_number <= 0:
            raise ValueError("Manual candidate page number is invalid")
        if not self.source_verified:
            raise ValueError("Source verification is required for manual entry")


FINAL_REVIEW_STATES = frozenset(
    {ReviewState.ACCEPTED, ReviewState.CORRECTED, ReviewState.REJECTED}
)
