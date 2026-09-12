from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["clinical"])


@router.get("/demo/encounters", response_model=list[dict])
async def list_encounters():
    return []


@router.post("/demo/encounters", status_code=201)
async def create_encounter():
    return {
        "id": str(uuid4()),
        "status": "draft",
        "synthetic": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
