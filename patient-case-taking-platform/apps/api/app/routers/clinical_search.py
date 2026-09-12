"""Authorized clinical search, timeline and CSV endpoints."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import ValidationError

from app.auth.dependencies import get_current_user
from app.auth.token import TokenPayload
from app.search.authorization import (
    SearchAuthorizationDenied,
    SearchIdentity,
    authorize_search_identity,
)
from app.search.contracts import ClinicalSearchQuery, ClinicalSearchResponse, SourceKind
from app.search.dependencies import get_clinical_search_service
from app.search.query import InvalidSearchCursor, decode_cursor
from app.search.service import ClinicalSearchService, ClinicalSearchUnavailable
from app.search.timeline import LongitudinalTimeline

router = APIRouter(tags=["clinical-search"])


def _correlation_id(request: Request) -> UUID:
    return request.state.correlation_id


def _identity(
    user: TokenPayload,
    *,
    patient_id: UUID | None,
    facility_ids: list[UUID] | None,
) -> SearchIdentity:
    try:
        return authorize_search_identity(
            user,
            requested_patient_id=patient_id,
            requested_facility_ids=set(facility_ids) if facility_ids else None,
        )
    except SearchAuthorizationDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _criteria(
    service: ClinicalSearchService,
    identity: SearchIdentity,
    *,
    q: str | None,
    source_kind: SourceKind | None,
    entity_type: str | None,
    from_date: datetime | None,
    to_date: datetime | None,
    page_size: int,
    cursor: str | None,
) -> ClinicalSearchQuery:
    try:
        criteria = service.criteria(
            identity,
            q=q,
            source_kind=source_kind,
            entity_type=entity_type,
            from_date=from_date,
            to_date=to_date,
            page_size=page_size,
            cursor=cursor,
        )
        if criteria.cursor is not None:
            decode_cursor(criteria.cursor)
        return criteria
    except (InvalidSearchCursor, ValidationError) as exc:
        raise HTTPException(status_code=422, detail="Invalid clinical search filters") from exc


@router.get("/api/v1/clinical-search", response_model=ClinicalSearchResponse)
async def clinical_search(
    request: Request,
    purpose: Literal["treatment"] = Query(...),
    patient_id: UUID | None = None,
    q: str | None = Query(default=None, max_length=200),
    source_kind: SourceKind | None = None,
    entity_type: str | None = Query(default=None, max_length=128),
    from_date: datetime | None = Query(default=None, alias="from"),
    to_date: datetime | None = Query(default=None, alias="to"),
    facility_ids: list[UUID] | None = Query(default=None, alias="facility_id"),
    page_size: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(default=None, max_length=1024),
    user: TokenPayload = Depends(get_current_user),
    service: ClinicalSearchService = Depends(get_clinical_search_service),
) -> ClinicalSearchResponse:
    del purpose
    identity = _identity(user, patient_id=patient_id, facility_ids=facility_ids)
    criteria = _criteria(
        service,
        identity,
        q=q,
        source_kind=source_kind,
        entity_type=entity_type,
        from_date=from_date,
        to_date=to_date,
        page_size=page_size,
        cursor=cursor,
    )
    try:
        return await service.search(
            identity,
            criteria,
            correlation_id=_correlation_id(request),
        )
    except ClinicalSearchUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


async def _timeline(
    request: Request,
    user: TokenPayload,
    service: ClinicalSearchService,
    *,
    patient_id: UUID | None,
    facility_ids: list[UUID] | None,
    source_kind: SourceKind | None,
    from_date: datetime | None,
    to_date: datetime | None,
) -> LongitudinalTimeline:
    identity = _identity(user, patient_id=patient_id, facility_ids=facility_ids)
    try:
        return await service.timeline(
            identity,
            source_kind=source_kind,
            from_date=from_date,
            to_date=to_date,
            correlation_id=_correlation_id(request),
        )
    except ClinicalSearchUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get(
    "/api/v1/clinical-search/timeline/{patient_id}",
    response_model=LongitudinalTimeline,
)
async def staff_timeline(
    request: Request,
    patient_id: UUID,
    purpose: Literal["treatment"] = Query(...),
    source_kind: SourceKind | None = None,
    from_date: datetime | None = Query(default=None, alias="from"),
    to_date: datetime | None = Query(default=None, alias="to"),
    facility_ids: list[UUID] | None = Query(default=None, alias="facility_id"),
    user: TokenPayload = Depends(get_current_user),
    service: ClinicalSearchService = Depends(get_clinical_search_service),
) -> LongitudinalTimeline:
    del purpose
    if user.role not in {"doctor", "nurse"}:
        raise HTTPException(status_code=403, detail="Clinical staff role required")
    return await _timeline(
        request,
        user,
        service,
        patient_id=patient_id,
        facility_ids=facility_ids,
        source_kind=source_kind,
        from_date=from_date,
        to_date=to_date,
    )


@router.get(
    "/api/v1/patient-portal/me/longitudinal-timeline",
    response_model=LongitudinalTimeline,
)
async def patient_timeline(
    request: Request,
    purpose: Literal["treatment"] = Query(...),
    source_kind: SourceKind | None = None,
    from_date: datetime | None = Query(default=None, alias="from"),
    to_date: datetime | None = Query(default=None, alias="to"),
    facility_ids: list[UUID] | None = Query(default=None, alias="facility_id"),
    user: TokenPayload = Depends(get_current_user),
    service: ClinicalSearchService = Depends(get_clinical_search_service),
) -> LongitudinalTimeline:
    del purpose
    if user.role != "patient":
        raise HTTPException(status_code=403, detail="Patient role required")
    return await _timeline(
        request,
        user,
        service,
        patient_id=None,
        facility_ids=facility_ids,
        source_kind=source_kind,
        from_date=from_date,
        to_date=to_date,
    )


@router.get("/api/v1/clinical-search/export.csv", response_class=Response)
async def export_clinical_search(
    request: Request,
    purpose: Literal["treatment"] = Query(...),
    patient_id: UUID | None = None,
    q: str | None = Query(default=None, max_length=200),
    source_kind: SourceKind | None = None,
    entity_type: str | None = Query(default=None, max_length=128),
    from_date: datetime | None = Query(default=None, alias="from"),
    to_date: datetime | None = Query(default=None, alias="to"),
    facility_ids: list[UUID] | None = Query(default=None, alias="facility_id"),
    user: TokenPayload = Depends(get_current_user),
    service: ClinicalSearchService = Depends(get_clinical_search_service),
) -> Response:
    del purpose
    if user.role not in {"doctor", "patient"}:
        raise HTTPException(status_code=403, detail="CSV export is not permitted")
    identity = _identity(user, patient_id=patient_id, facility_ids=facility_ids)
    criteria = _criteria(
        service,
        identity,
        q=q,
        source_kind=source_kind,
        entity_type=entity_type,
        from_date=from_date,
        to_date=to_date,
        page_size=50,
        cursor=None,
    )
    try:
        content = await service.export_csv(
            identity,
            criteria,
            correlation_id=_correlation_id(request),
        )
    except ClinicalSearchUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(
        content=content.encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": 'attachment; filename="medikiosk-clinical-search.csv"',
            "X-Content-Type-Options": "nosniff",
        },
    )
