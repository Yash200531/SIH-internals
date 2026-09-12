from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.documents.promotion import DocumentTimelineEntry
from app.patient_portal.contracts import (
    PatientDashboardResponse,
    PatientReportDetail,
    PatientReportListItem,
)
from app.schemas.reviewed_document import TimelineEntryResponse
from app.summary_workflow.contracts import SummaryRecord, SummaryStatus
from app.summary_workflow.repository import SummaryNotFound, SummaryRepository


@dataclass(frozen=True)
class PatientIdentity:
    tenant_id: UUID
    patient_id: UUID
    facility_ids: set[UUID]


class TimelineRepository(Protocol):
    async def list_timeline(
        self,
        *,
        tenant_id: UUID,
        patient_id: UUID,
        facility_ids: set[UUID],
        limit: int = 100,
    ) -> list[DocumentTimelineEntry]: ...

    async def count_timeline(
        self,
        *,
        tenant_id: UUID,
        patient_id: UUID,
        facility_ids: set[UUID],
    ) -> int: ...


class PatientReportNotFound(Exception):
    pass


class PatientPortalService:
    def __init__(
        self,
        summaries: SummaryRepository,
        timeline: TimelineRepository,
    ) -> None:
        self._summaries = summaries
        self._timeline = timeline

    async def list_reports(
        self, identity: PatientIdentity, *, limit: int = 100
    ) -> list[PatientReportListItem]:
        records = await self._summaries.list_signed_for_patient(
            tenant_id=identity.tenant_id,
            patient_id=identity.patient_id,
            facility_ids=identity.facility_ids,
            limit=limit,
        )
        return [self._list_item(record) for record in records]

    async def get_report(
        self, identity: PatientIdentity, report_id: UUID
    ) -> PatientReportDetail:
        try:
            record = await self._summaries.get(
                tenant_id=identity.tenant_id, summary_id=report_id
            )
        except SummaryNotFound as exc:
            raise PatientReportNotFound("Patient report not found") from exc
        if (
            record.patient_id != identity.patient_id
            or record.facility_id not in identity.facility_ids
            or record.status is not SummaryStatus.SIGNED
            or record.signed_at is None
            or record.signature_sha256 is None
        ):
            raise PatientReportNotFound("Patient report not found")
        return PatientReportDetail(
            **self._list_item(record).model_dump(),
            generation=record.generation,
            content=record.content,
            evidence=record.evidence,
            schema_version=record.schema_version,
        )

    async def list_timeline(
        self, identity: PatientIdentity, *, limit: int = 100
    ) -> list[TimelineEntryResponse]:
        entries = await self._timeline.list_timeline(
            tenant_id=identity.tenant_id,
            patient_id=identity.patient_id,
            facility_ids=identity.facility_ids,
            limit=limit,
        )
        return [TimelineEntryResponse.model_validate(entry) for entry in entries]

    async def dashboard(self, identity: PatientIdentity) -> PatientDashboardResponse:
        reports = await self.list_reports(identity, limit=3)
        timeline = await self.list_timeline(identity, limit=5)
        report_count = await self._summaries.count_signed_for_patient(
            tenant_id=identity.tenant_id,
            patient_id=identity.patient_id,
            facility_ids=identity.facility_ids,
        )
        timeline_count = await self._timeline.count_timeline(
            tenant_id=identity.tenant_id,
            patient_id=identity.patient_id,
            facility_ids=identity.facility_ids,
        )
        return PatientDashboardResponse(
            patient_id=identity.patient_id,
            signed_report_count=report_count,
            reviewed_timeline_count=timeline_count,
            recent_reports=reports,
            recent_timeline=timeline,
        )

    async def render_report_download(
        self, identity: PatientIdentity, report_id: UUID
    ) -> str:
        report = await self.get_report(identity, report_id)
        content = report.content
        sections = [
            "MEDIKIOSK SIGNED PATIENT REPORT",
            f"Report ID: {report.id}",
            f"Encounter ID: {report.encounter_id}",
            f"Signed at: {report.signed_at.isoformat()}",
            f"Integrity SHA-256: {report.signature_sha256}",
            f"Schema: {report.schema_version}",
            "",
            "CHIEF COMPLAINT",
            content.chief_complaint,
            "",
            "HISTORY OF PRESENT ILLNESS",
            *self._lines(content.history_of_present_illness),
            "",
            "RELEVANT NEGATIVES",
            *self._lines(content.relevant_negatives),
            "",
            "REVIEWED DOCUMENT FACTS",
            *self._lines(content.document_facts),
            "",
            "SAFETY FLAGS",
            *self._lines(content.red_flags),
            "",
            "UNCERTAINTIES / FOLLOW-UP",
            *self._lines(content.uncertainties),
            "",
            "This is clinician-signed information, not emergency advice.",
        ]
        return "\n".join(sections) + "\n"

    @staticmethod
    def _lines(values: list[str]) -> list[str]:
        return [f"- {value}" for value in values] or ["- None recorded"]

    @staticmethod
    def _list_item(record: SummaryRecord) -> PatientReportListItem:
        if record.signed_at is None or record.signature_sha256 is None:
            raise ValueError("Signed report metadata is incomplete")
        return PatientReportListItem(
            id=record.id,
            encounter_id=record.encounter_id,
            facility_id=record.facility_id,
            title=record.content.chief_complaint,
            signed_at=record.signed_at,
            signature_sha256=record.signature_sha256,
            provider=record.provider,
            degraded=record.degraded,
        )
