"""Narrow deterministic extraction for document-stated prescription fields."""

import re
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from app.documents.ocr_artifact import DocumentOcrArtifact, OcrArtifactRegion

EntityType = Literal[
    "document_date",
    "medication_statement",
    "strength",
    "route",
    "frequency",
    "duration",
    "instructions",
]
Temporality = Literal["documented", "historical", "future", "unknown"]
Subject = Literal["patient", "other", "unknown"]
_PARSER_VERSION: Literal["prescription-rules.v1"] = "prescription-rules.v1"
_DATE = re.compile(r"(?i)\b(?:date|dated)\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})\b")
_MEDICATION_PREFIX = re.compile(
    r"(?i)\b(?:rx\s*)?(?:tab(?:let)?|cap(?:sule)?|syp|syrup|inj(?:ection)?|"
    r"eye\s+drops?|drops?)\.?\s+"
)
_STRENGTH = re.compile(r"(?i)\b(\d+(?:[\.,]\d+)?)\s*(mcg|mg|g|ml|%)(?!\w)")
_DURATION = re.compile(r"(?i)(?:\bfor\s+|\bx\s*)(\d+)\s*(day|week|month)s?\b")
_ROUTES = {
    "po": "oral",
    "oral": "oral",
    "iv": "intravenous",
    "im": "intramuscular",
    "sc": "subcutaneous",
    "sl": "sublingual",
    "pr": "rectal",
    "topical": "topical",
    "inhaled": "inhaled",
}
_FREQUENCIES = {
    "od": "once_daily",
    "once daily": "once_daily",
    "bd": "twice_daily",
    "bid": "twice_daily",
    "twice daily": "twice_daily",
    "tds": "three_times_daily",
    "tid": "three_times_daily",
    "qid": "four_times_daily",
    "hs": "at_bedtime",
    "sos": "as_needed",
    "prn": "as_needed",
}
_INSTRUCTIONS = (
    "after food",
    "before food",
    "with food",
    "with meals",
    "at bedtime",
)


class SourceRegionRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_id: UUID
    page_artifact_id: UUID
    ocr_artifact_id: UUID
    region_id: UUID
    page_number: int = Field(gt=0)
    page_width: int = Field(gt=0)
    page_height: int = Field(gt=0)
    bbox: tuple[int, int, int, int] | None = None
    polygon: tuple[tuple[int, int], ...] | None = None


class ExtractionCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_id: UUID
    entity_type: EntityType
    raw_source_text: str = Field(min_length=1, max_length=20_000)
    normalized_value: str | None = Field(default=None, max_length=2_000)
    unit: str | None = Field(default=None, max_length=32)
    source: SourceRegionRef
    parser_version: Literal["prescription-rules.v1"] = _PARSER_VERSION
    parser_signal: str = Field(min_length=1, max_length=128)
    model_signal: None = None
    negated: bool = False
    temporality: Temporality
    subject: Subject
    uncertainty: str | None = Field(default=None, max_length=128)
    document_statement: Literal[True] = True
    clinician_confirmed_current: Literal[False] = False
    review_state: Literal["unreviewed"] = "unreviewed"


class PrescriptionExtractionDraft(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal["DocumentExtractionDraft.v1"] = "DocumentExtractionDraft.v1"
    draft_id: UUID
    tenant_id: UUID
    document_id: UUID
    ocr_run_id: UUID
    document_class: Literal["prescription"] = "prescription"
    parser_version: Literal["prescription-rules.v1"] = _PARSER_VERSION
    candidates: tuple[ExtractionCandidate, ...]
    warnings: tuple[str, ...] = ()
    review_required: Literal[True] = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def _line_context(line: str) -> tuple[bool, Temporality, Subject, str | None]:
    lowered = line.casefold()
    negated = any(
        phrase in lowered
        for phrase in ("stopped", "stop ", "discontinue", "no longer", "not taking")
    )
    temporality: Temporality
    if any(phrase in lowered for phrase in ("previously", "history of", "past ")):
        temporality = "historical"
    elif any(phrase in lowered for phrase in ("start tomorrow", "to start", "from tomorrow")):
        temporality = "future"
    else:
        temporality = "documented"
    subject: Subject = (
        "other"
        if re.search(r"(?i)\b(mother|father|caregiver|husband|wife)\b", line)
        else "patient"
    )
    uncertainty = (
        "uncertain_source_assertion"
        if re.search(r"(?i)\b(possible|possibly|maybe|uncertain)\b|\?", line)
        else None
    )
    return negated, temporality, subject, uncertainty


def _token_match(line: str, values: dict[str, str]) -> tuple[str, str] | None:
    for token in sorted(values, key=len, reverse=True):
        match = re.search(rf"(?i)\b{re.escape(token)}\b", line)
        if match:
            return match.group(0), values[token]
    return None


class PrescriptionRulesExtractor:
    """Conservative parser that emits only explicit document statements."""

    def extract(self, artifacts: list[DocumentOcrArtifact]) -> PrescriptionExtractionDraft:
        if not artifacts:
            raise ValueError("Prescription extraction requires OCR artifacts")
        first = artifacts[0]
        if any(
            artifact.tenant_id != first.tenant_id
            or artifact.document_id != first.document_id
            or artifact.ocr_run_id != first.ocr_run_id
            for artifact in artifacts
        ):
            raise ValueError("OCR artifacts must belong to one document run")
        draft_id = uuid5(first.ocr_run_id, _PARSER_VERSION)
        candidates: list[ExtractionCandidate] = []
        warnings: list[str] = []
        for artifact in sorted(artifacts, key=lambda item: item.page_number):
            for region in artifact.regions:
                self._extract_region(
                    draft_id,
                    artifact,
                    region,
                    candidates,
                    warnings,
                )
        return PrescriptionExtractionDraft(
            draft_id=draft_id,
            tenant_id=first.tenant_id,
            document_id=first.document_id,
            ocr_run_id=first.ocr_run_id,
            candidates=tuple(candidates),
            warnings=tuple(dict.fromkeys(warnings)),
        )

    def _extract_region(
        self,
        draft_id: UUID,
        artifact: DocumentOcrArtifact,
        region: OcrArtifactRegion,
        candidates: list[ExtractionCandidate],
        warnings: list[str],
    ) -> None:
        line = " ".join(region.text.split())
        lowered = line.casefold()
        if re.match(r"(?i)^\s*(diagnosis|dx)\s*:", line):
            warnings.append("unsupported_assertion:diagnosis")
            return
        date_match = _DATE.search(line)
        if date_match:
            try:
                parsed_date = datetime.strptime(
                    date_match.group(1).replace("-", "/"), "%d/%m/%Y"
                ).date()
            except ValueError:
                warnings.append("invalid_document_date")
            else:
                self._append(
                    candidates,
                    draft_id,
                    artifact,
                    region,
                    "document_date",
                    parsed_date.isoformat(),
                    None,
                    "explicit_date_label",
                )

        # A dosage instruction may contain "tablet" without naming any drug.
        if re.match(r"(?i)^(?:take|use|administer|apply)\b", line):
            warnings.append("standalone_instruction_requires_review")
            return
        prefix = _MEDICATION_PREFIX.search(line)
        if prefix is None:
            # Printed prescriptions also use NAME + numeric strength without
            # a dosage-form prefix. Keep these explicitly uncertain for review.
            strength = _STRENGTH.search(line)
            if strength is None or not re.fullmatch(r"[A-Za-z][A-Za-z .+/-]{1,79}", line[:strength.start()].strip()):
                return
            medication_tail = line
        else:
            medication_tail = line[prefix.end() :].strip()
        strength_match = _STRENGTH.search(medication_tail)
        stop_at = strength_match.start() if strength_match else len(medication_tail)
        if strength_match is None:
            positions = [
                match.start()
                for token in (*_ROUTES, *_FREQUENCIES)
                if (match := re.search(rf"(?i)\b{re.escape(token)}\b", medication_tail))
            ]
            if positions:
                stop_at = min(positions)
        medication = medication_tail[:stop_at].strip(" .,:;-")
        if not medication:
            warnings.append("missing_medication_name")
            return

        negated, temporality, subject, uncertainty = _line_context(line)
        if prefix is None:
            uncertainty = uncertainty or "medication_name_requires_verification"
        context = (negated, temporality, subject, uncertainty)
        self._append(
            candidates,
            draft_id,
            artifact,
            region,
            "medication_statement",
            medication,
            None,
            "explicit_medication_form_prefix" if prefix else "name_and_strength_requires_review",
            context,
        )
        if strength_match:
            value = strength_match.group(1).replace(",", ".")
            self._append(
                candidates,
                draft_id,
                artifact,
                region,
                "strength",
                value,
                strength_match.group(2).lower(),
                "explicit_number_and_unit",
                context,
            )
        route = _token_match(line, _ROUTES)
        if route:
            self._append(
                candidates,
                draft_id,
                artifact,
                region,
                "route",
                route[1],
                None,
                f"route_token:{route[0].upper()}",
                context,
            )
        frequency = _token_match(line, _FREQUENCIES)
        if frequency:
            if frequency[0].casefold() == "od" and any(
                word in lowered for word in ("eye", "ophthalmic", "drops")
            ):
                warnings.append("ambiguous_abbreviation:OD")
            else:
                self._append(
                    candidates,
                    draft_id,
                    artifact,
                    region,
                    "frequency",
                    frequency[1],
                    None,
                    f"frequency_token:{frequency[0].upper()}",
                    context,
                )
        duration = _DURATION.search(line)
        if duration:
            designator = {"day": "D", "week": "W", "month": "M"}[
                duration.group(2).casefold()
            ]
            self._append(
                candidates,
                draft_id,
                artifact,
                region,
                "duration",
                f"P{int(duration.group(1))}{designator}",
                None,
                "explicit_duration",
                context,
            )
        for instruction in _INSTRUCTIONS:
            if instruction in lowered:
                self._append(
                    candidates,
                    draft_id,
                    artifact,
                    region,
                    "instructions",
                    instruction,
                    None,
                    "explicit_instruction_phrase",
                    context,
                )
                break

    @staticmethod
    def _append(
        candidates: list[ExtractionCandidate],
        draft_id: UUID,
        artifact: DocumentOcrArtifact,
        region: OcrArtifactRegion,
        entity_type: EntityType,
        normalized_value: str,
        unit: str | None,
        parser_signal: str,
        context: tuple[bool, Temporality, Subject, str | None] | None = None,
    ) -> None:
        negated, temporality, subject, uncertainty = context or (
            False,
            "documented",
            "patient",
            None,
        )
        ordinal = len(candidates) + 1
        candidates.append(
            ExtractionCandidate(
                candidate_id=uuid5(draft_id, f"candidate:{ordinal}"),
                entity_type=entity_type,
                raw_source_text=region.text,
                normalized_value=normalized_value,
                unit=unit,
                source=SourceRegionRef(
                    document_id=artifact.document_id,
                    page_artifact_id=artifact.page_artifact_id,
                    ocr_artifact_id=artifact.artifact_id,
                    region_id=region.region_id,
                    page_number=artifact.page_number,
                    page_width=artifact.width,
                    page_height=artifact.height,
                    bbox=region.bbox,
                    polygon=region.polygon,
                ),
                parser_signal=parser_signal,
                negated=negated,
                temporality=temporality,
                subject=subject,
                uncertainty=uncertainty,
            )
        )
