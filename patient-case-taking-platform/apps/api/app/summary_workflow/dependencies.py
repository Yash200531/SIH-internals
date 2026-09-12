"""FastAPI dependencies for the durable Phase 8 workflow."""

from fastapi import HTTPException

from app.config import settings
from app.database import get_postgres_pool
from app.llm.service import get_llm_router
from app.summary_workflow.context import PostgresSummaryContextRepository, SummaryContextRepository
from app.summary_workflow.repository import PostgresSummaryRepository, SummaryRepository
from app.summary_workflow.service import SummaryWorkflowService


def _require_enabled() -> None:
    if not settings.SUMMARY_WORKFLOW_ENABLED:
        raise HTTPException(status_code=503, detail="Summary workflow is not enabled")
    if settings.LLM_PROVIDER != "mock":
        raise HTTPException(status_code=503, detail="Summary workflow requires mock provider")


async def get_summary_repository() -> SummaryRepository:
    _require_enabled()
    return PostgresSummaryRepository(await get_postgres_pool())


async def get_summary_context_repository() -> SummaryContextRepository:
    _require_enabled()
    return PostgresSummaryContextRepository(await get_postgres_pool())


async def get_summary_workflow_service() -> SummaryWorkflowService:
    return SummaryWorkflowService(await get_summary_repository(), get_llm_router())
