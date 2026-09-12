"""Audit query endpoints.
Reads from the centralized audit_emitter — the same store all routers write to."""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Query

from app.audit.emitter import audit_emitter

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


@router.get("")
async def query_audit_log(
    tenant_id: UUID = Query(...),
    resource_type: Optional[str] = Query(None),
    resource_id: Optional[UUID] = Query(None),
    action: Optional[str] = Query(None),
):
    """Query immutable audit events. All sensitive operations emit here."""
    events = audit_emitter.query(
        tenant_id=tenant_id,
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
    )
    return [
        {
            "id": str(e["id"]),
            "tenant_id": str(e["tenant_id"]),
            "actor_id": str(e["actor_id"]) if e["actor_id"] else None,
            "actor_type": e["actor_type"],
            "actor_role": e["actor_role"],
            "action": e["action"],
            "resource_type": e["resource_type"],
            "resource_id": str(e["resource_id"]) if e["resource_id"] else None,
            "purpose": e["purpose"],
            "outcome": e["outcome"],
            "outcome_detail": e["outcome_detail"],
            "facility_id": str(e["facility_id"]) if e["facility_id"] else None,
            "metadata": e["metadata"],
            "created_at": e["created_at"],
        }
        for e in events
    ]


@router.get("/actor/{actor_id}")
async def audit_trail_for_actor(actor_id: UUID, tenant_id: UUID = Query(...)):
    events = audit_emitter.query(tenant_id=tenant_id, actor_id=actor_id)
    return [
        {
            "id": str(e["id"]),
            "action": e["action"],
            "resource_type": e["resource_type"],
            "outcome": e["outcome"],
            "created_at": e["created_at"],
        }
        for e in events
    ]
