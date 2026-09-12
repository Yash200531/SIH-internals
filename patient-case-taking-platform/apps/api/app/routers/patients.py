from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query

from app.audit.emitter import audit_emitter, safe_uuid
from app.auth.dependencies import get_current_user
from app.auth.token import TokenPayload
from app.models.external_id import ExternalId
from app.models.patient import PatientProfile
from app.schemas.patient import PatientCreate

router = APIRouter(prefix="/api/v1/patients", tags=["patients"])

_patients: dict[str, PatientProfile] = {}
_external_ids: dict[str, ExternalId] = {}


def _generate_mrn() -> str:
    return f"MRN-{uuid4().hex[:10].upper()}"


def _to_response(p: PatientProfile) -> dict:
    return {
        "id": p.id,
        "tenant_id": p.tenant_id,
        "internal_mrn": p.internal_mrn,
        "full_name": p.full_name,
        "date_of_birth": p.date_of_birth,
        "gender": p.gender,
        "phone": p.phone,
        "language_preference": p.language_preference,
        "abha_verified": p.abha_verified,
        "created_at": p.created_at,
        "version": p.version,
    }


@router.post("", status_code=201)
async def create_patient(
    body: PatientCreate,
    tenant_id: UUID = Query(...),
    user: TokenPayload = Depends(get_current_user),
):
    patient = PatientProfile(
        tenant_id=tenant_id,
        internal_mrn=_generate_mrn(),
        full_name=body.full_name,
        date_of_birth=body.date_of_birth,
        gender=body.gender,
        phone=body.phone,
        language_preference=body.language_preference,
        emergency_contact=body.emergency_contact,
    )
    _patients[str(patient.id)] = patient

    audit_emitter.emit(
        tenant_id=tenant_id,
        actor_id=safe_uuid(user.user_id),
        actor_type="staff",
        actor_role=user.role,
        action="create",
        resource_type="patient",
        resource_id=patient.id,
        outcome="success",
    )

    return _to_response(patient)


@router.get("/search")
async def search_patients(
    query: str = Query(...),
    tenant_id: UUID = Query(...),
    facility_id: Optional[UUID] = Query(None),
    user: TokenPayload = Depends(get_current_user),
):
    q = query.lower()
    results = []
    for p in _patients.values():
        if p.tenant_id != tenant_id:
            continue
        if (
            q in p.full_name.lower()
            or q in p.internal_mrn.lower()
            or (p.phone and q in p.phone)
        ):
            results.append(_to_response(p))
    return results


@router.get("/{patient_id}")
async def get_patient(
    patient_id: UUID,
    user: TokenPayload = Depends(get_current_user),
):
    patient = _patients.get(str(patient_id))
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    audit_emitter.emit(
        tenant_id=patient.tenant_id,
        actor_id=safe_uuid(user.user_id),
        actor_type="staff",
        actor_role=user.role,
        action="read",
        resource_type="patient",
        resource_id=patient.id,
        outcome="success",
    )

    return _to_response(patient)


@router.put("/{patient_id}")
async def update_patient(
    patient_id: UUID,
    body: PatientCreate,
    user: TokenPayload = Depends(get_current_user),
):
    patient = _patients.get(str(patient_id))
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    patient.full_name = body.full_name
    patient.date_of_birth = body.date_of_birth
    patient.gender = body.gender
    patient.phone = body.phone
    patient.language_preference = body.language_preference
    patient.emergency_contact = body.emergency_contact
    patient.version += 1
    patient.updated_at = datetime.now(timezone.utc)

    audit_emitter.emit(
        tenant_id=patient.tenant_id,
        actor_id=safe_uuid(user.user_id),
        actor_type="staff",
        actor_role=user.role,
        action="update",
        resource_type="patient",
        resource_id=patient.id,
        outcome="success",
    )

    return _to_response(patient)


@router.post("/{patient_id}/abha", status_code=201)
async def link_abha(
    patient_id: UUID,
    abha_number: str = Query(...),
    abha_address: str = Query(...),
    user: TokenPayload = Depends(get_current_user),
):
    patient = _patients.get(str(patient_id))
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    patient.abha_number = abha_number
    patient.abha_address = abha_address
    patient.abha_verified = True
    patient.abha_linked_at = datetime.now(timezone.utc)
    patient.version += 1

    ext = ExternalId(
        tenant_id=patient.tenant_id,
        patient_id=patient.id,
        id_type="abha_number",
        id_value=abha_number,
        is_verified=True,
        verified_at=datetime.now(timezone.utc),
    )
    _external_ids[str(ext.id)] = ext

    audit_emitter.emit(
        tenant_id=patient.tenant_id,
        actor_id=safe_uuid(user.user_id),
        actor_type="staff",
        actor_role=user.role,
        action="abha_link",
        resource_type="patient",
        resource_id=patient.id,
        outcome="success",
        audit_metadata={"abha_number": abha_number},
    )

    return _to_response(patient)
