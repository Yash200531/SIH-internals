"""Phase 5 task-level clinical AI endpoints."""

from fastapi import APIRouter, Depends

from app.llm.schemas import (
    ClinicalSummaryRequest,
    ClinicalSummaryResponse,
    DialogueRequest,
    DialogueResponse,
    ProviderHealthResponse,
)
from app.llm.service import LLMRouter, get_llm_router

router = APIRouter(prefix="/api/v1/clinical-ai", tags=["clinical-ai"])


@router.get("/health", response_model=ProviderHealthResponse)
async def provider_health(service: LLMRouter = Depends(get_llm_router)) -> ProviderHealthResponse:
    return ProviderHealthResponse(
        provider=service.provider.name,
        ready=await service.provider.health(),
        external_network_used=service.provider.external_network_used,
    )


@router.post("/dialogue/next", response_model=DialogueResponse)
async def next_question(
    body: DialogueRequest, service: LLMRouter = Depends(get_llm_router)
) -> DialogueResponse:
    return await service.next_question(body)


@router.post("/summaries/generate", response_model=ClinicalSummaryResponse)
async def generate_summary(
    body: ClinicalSummaryRequest, service: LLMRouter = Depends(get_llm_router)
) -> ClinicalSummaryResponse:
    return await service.generate_summary(body)
