from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from app.models.clinical_summary import ClinicalSummary
from app.schemas.clinical_summary import SummaryCreate, SummarySign

router = APIRouter(prefix="/api/v1/summaries", tags=["summaries"])

_summaries: dict[str, ClinicalSummary] = {}


def _to_response(s: ClinicalSummary) -> dict:
    return {
        "id": s.id,
        "tenant_id": s.tenant_id,
        "encounter_id": s.encounter_id,
        "summary_type": s.summary_type,
        "content": s.content,
        "status": s.status,
        "generated_by": s.generated_by,
        "version": s.version,
        "created_at": s.created_at,
    }


@router.post("", status_code=201)
async def create_summary(body: SummaryCreate, tenant_id: UUID = Query(...)):
    summary = ClinicalSummary(
        tenant_id=tenant_id,
        facility_id=UUID(int=0),  # placeholder
        patient_id=body.patient_id,
        encounter_id=body.encounter_id,
        summary_type=body.summary_type,
        content=body.content,
        raw_text=body.raw_text,
        generated_by=body.generated_by,
        model_version=body.model_version,
        source_answers=body.source_answers,
        source_documents=body.source_documents,
    )
    _summaries[str(summary.id)] = summary
    return _to_response(summary)


@router.get("/{summary_id}")
async def get_summary(summary_id: UUID):
    summary = _summaries.get(str(summary_id))
    if not summary:
        raise HTTPException(status_code=404, detail="Summary not found")
    return _to_response(summary)


@router.get("")
async def list_summaries(encounter_id: Optional[UUID] = Query(None), tenant_id: UUID = Query(...)):
    results = [
        _to_response(s)
        for s in _summaries.values()
        if s.tenant_id == tenant_id and (encounter_id is None or s.encounter_id == encounter_id)
    ]
    return results


@router.post("/{summary_id}/review")
async def review_summary(summary_id: UUID):
    summary = _summaries.get(str(summary_id))
    if not summary:
        raise HTTPException(status_code=404, detail="Summary not found")
    if summary.status != "draft":
        raise HTTPException(status_code=409, detail=f"Cannot review summary in status '{summary.status}'")
    summary.status = "review"
    summary.reviewed_at = datetime.now(timezone.utc)
    return _to_response(summary)


@router.post("/{summary_id}/sign")
async def sign_summary(summary_id: UUID, body: SummarySign):
    summary = _summaries.get(str(summary_id))
    if not summary:
        raise HTTPException(status_code=404, detail="Summary not found")
    if summary.status not in ("draft", "review"):
        raise HTTPException(status_code=409, detail=f"Cannot sign summary in status '{summary.status}'")
    summary.status = "signed"
    summary.signed_by = body.signed_by
    summary.signed_at = datetime.now(timezone.utc)
    summary.clinician_edits = body.clinician_edits
    summary.version += 1
    return _to_response(summary)
