"""Bounded FHIR R4 search-set facade over canonical reviewed records."""

from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.auth.dependencies import get_current_user
from app.auth.token import TokenPayload
from app.search.authorization import SearchAuthorizationDenied, authorize_search_identity
from app.search.contracts import ClinicalSearchRecord, SourceKind
from app.search.dependencies import get_clinical_search_service
from app.search.service import ClinicalSearchService, ClinicalSearchUnavailable

router = APIRouter(prefix="/api/v1/fhir-search", tags=["fhir-search"])

_COMMON_PARAMETERS = {"patient", "purpose", "facility_id", "_count", "page"}
_RESOURCE_PARAMETERS = {
    "DocumentReference": _COMMON_PARAMETERS | {"date"},
    "Basic": _COMMON_PARAMETERS | {"created", "code"},
}


@router.get("/{resource_type}")
async def fhir_search(
    resource_type: str,
    request: Request,
    user: TokenPayload = Depends(get_current_user),
    service: ClinicalSearchService = Depends(get_clinical_search_service),
):
    if resource_type not in _RESOURCE_PARAMETERS:
        return _outcome(400, "not-supported", "FHIR resource search is not supported")
    unexpected = set(request.query_params.keys()) - _RESOURCE_PARAMETERS[resource_type]
    if unexpected:
        return _outcome(400, "not-supported", "FHIR search parameter is not supported")
    if request.query_params.get("purpose") != "treatment":
        return _outcome(400, "required", "purpose=treatment is required")

    try:
        requested_patient = _optional_uuid(request.query_params.get("patient"), "patient")
        facilities = {
            _required_uuid(value, "facility_id")
            for value in request.query_params.getlist("facility_id")
        }
        count = _bounded_int(request.query_params.get("_count"), "_count", 20, 1, 50)
        page = _bounded_int(request.query_params.get("page"), "page", 1, 1, 10_000)
        if resource_type == "DocumentReference":
            from_date, to_date = _date_range(request.query_params.get("date"))
            source_kind = SourceKind.SIGNED_SUMMARY
            entity_type = None
        else:
            from_date, to_date = _date_range(request.query_params.get("created"))
            source_kind = SourceKind.REVIEWED_FACT
            entity_type = request.query_params.get("code")
            if entity_type is not None:
                entity_type = " ".join(entity_type.split())
                if not entity_type or len(entity_type) > 128:
                    raise ValueError("code is invalid")
    except ValueError as exc:
        return _outcome(400, "invalid", str(exc))

    try:
        identity = authorize_search_identity(
            user,
            requested_patient_id=requested_patient,
            requested_facility_ids=facilities or None,
        )
    except SearchAuthorizationDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    try:
        result = await service.fhir_records(
            identity,
            source_kind=source_kind,
            entity_type=entity_type,
            from_date=from_date,
            to_date=to_date,
            page=page,
            page_size=count,
            correlation_id=request.state.correlation_id,
        )
    except ClinicalSearchUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    entries = [
        {
            "fullUrl": f"urn:uuid:{record.source_id}",
            "resource": _document_reference(record)
            if source_kind is SourceKind.SIGNED_SUMMARY
            else _basic(record),
            "search": {"mode": "match"},
        }
        for record in result.records
    ]
    links = [{"relation": "self", "url": str(request.url)}]
    if result.has_next:
        links.append(
            {"relation": "next", "url": str(request.url.include_query_params(page=page + 1))}
        )
    return {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": result.total,
        "link": links,
        "entry": entries,
    }


def _document_reference(record: ClinicalSearchRecord) -> dict[str, object]:
    return {
        "resourceType": "DocumentReference",
        "id": str(record.source_id),
        "meta": {"security": _security(record)},
        "status": "current",
        "type": {"text": "Clinician-signed summary"},
        "subject": {"reference": f"Patient/{record.patient_id}"},
        "date": record.occurred_at.isoformat(),
        "description": record.title,
        "context": {
            "encounter": [{"reference": f"Encounter/{record.encounter_id}"}]
        },
        "content": [
            {
                "attachment": {
                    "contentType": "text/plain",
                    "title": record.title,
                }
            }
        ],
    }


def _basic(record: ClinicalSearchRecord) -> dict[str, object]:
    extensions: list[dict[str, object]] = [
        {
            "url": "https://medikiosk.example/fhir/StructureDefinition/statement-status",
            "valueCode": record.statement_status or "document_stated",
        },
        {
            "url": "https://medikiosk.example/fhir/StructureDefinition/encounter-reference",
            "valueReference": {"reference": f"Encounter/{record.encounter_id}"},
        },
    ]
    if record.document_id is not None:
        extensions.append(
            {
                "url": "https://medikiosk.example/fhir/StructureDefinition/source-document",
                "valueReference": {"reference": f"DocumentReference/{record.document_id}"},
            }
        )
    return {
        "resourceType": "Basic",
        "id": str(record.source_id),
        "meta": {"security": _security(record)},
        "code": {"text": record.entity_type or "Reviewed document fact"},
        "subject": {"reference": f"Patient/{record.patient_id}"},
        "created": record.occurred_at.isoformat(),
        "extension": extensions,
    }


def _security(record: ClinicalSearchRecord) -> list[dict[str, str]]:
    return [
        {"system": "https://medikiosk.example/fhir/security-label", "code": label}
        for label in record.security_labels
    ]


def _date_range(value: str | None) -> tuple[datetime | None, datetime | None]:
    if value is None:
        return None, None
    if not value or len(value) > 64:
        raise ValueError("FHIR date search is invalid")
    prefix = value[:2] if value[:2] in {"eq", "ge", "gt", "le", "lt"} else "eq"
    raw = value[2:] if value[:2] in {"eq", "ge", "gt", "le", "lt"} else value
    try:
        if len(raw) == 10:
            parsed_date = date.fromisoformat(raw)
            start = datetime.combine(parsed_date, time.min, tzinfo=UTC)
            end = datetime.combine(parsed_date, time.max, tzinfo=UTC)
        else:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            start = parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
            end = start
    except ValueError as exc:
        raise ValueError("FHIR date search is invalid") from exc
    if prefix == "eq":
        return start, end
    if prefix == "ge":
        return start, None
    if prefix == "gt":
        return end + timedelta(microseconds=1), None
    if prefix == "le":
        return None, end
    return None, start - timedelta(microseconds=1)


def _optional_uuid(value: str | None, name: str) -> UUID | None:
    return None if value is None else _required_uuid(value, name)


def _required_uuid(value: str, name: str) -> UUID:
    try:
        return UUID(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} is invalid") from exc


def _bounded_int(
    value: str | None, name: str, default: int, minimum: int, maximum: int
) -> int:
    try:
        parsed = default if value is None else int(value)
    except ValueError as exc:
        raise ValueError(f"{name} is invalid") from exc
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{name} is invalid")
    return parsed


def _outcome(status_code: int, code: str, diagnostics: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "resourceType": "OperationOutcome",
            "issue": [
                {
                    "severity": "error",
                    "code": code,
                    "diagnostics": diagnostics[:200],
                }
            ],
        },
    )
