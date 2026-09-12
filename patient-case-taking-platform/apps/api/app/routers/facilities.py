from typing import List
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from app.models.facility import Facility
from app.schemas.facility import FacilityCreate

router = APIRouter(prefix="/api/v1/facilities", tags=["facilities"])

_facilities: dict[str, Facility] = {}


def _to_response(f: Facility) -> dict:
    return {
        "id": f.id,
        "tenant_id": f.tenant_id,
        "name": f.name,
        "slug": f.slug,
        "is_active": f.is_active,
        "created_at": f.created_at,
    }


@router.post("", status_code=201)
async def create_facility(body: FacilityCreate, tenant_id: UUID = Query(...)):
    facility = Facility(
        tenant_id=tenant_id,
        name=body.name,
        slug=body.slug,
        address=body.address,
        phone=body.phone,
    )
    _facilities[str(facility.id)] = facility
    return _to_response(facility)


@router.get("", response_model=List[dict])
async def list_facilities(tenant_id: UUID = Query(...)):
    return [_to_response(f) for f in _facilities.values() if f.tenant_id == tenant_id]


@router.get("/{facility_id}")
async def get_facility(facility_id: UUID):
    facility = _facilities.get(str(facility_id))
    if not facility:
        raise HTTPException(status_code=404, detail="Facility not found")
    return _to_response(facility)
