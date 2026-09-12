"""Schema-constrained clinical task router with audit-safe metadata."""

from typing import Any, TypeVar
from uuid import UUID

from pydantic import BaseModel, ValidationError

from app.audit.emitter import audit_emitter
from app.config import settings
from app.llm.providers import LLMProvider, build_provider
from app.llm.schemas import (
    ClinicalSummaryRequest,
    ClinicalSummaryResponse,
    DialogueRequest,
    DialogueResponse,
)
from app.rules.triage import detect_red_flags

ResponseT = TypeVar("ResponseT", bound=BaseModel)


class LLMRouter:
    """Routes bounded task payloads through an approved provider contract."""

    def __init__(self, provider: LLMProvider, max_attempts: int = 3):
        self.provider = provider
        self.max_attempts = max(1, min(max_attempts, 3))

    async def next_question(self, request: DialogueRequest) -> DialogueResponse:
        payload = request.model_dump(mode="json")
        result = await self._validated_generate(
            task="dialogue.next_question",
            payload=payload,
            response_model=DialogueResponse,
            fallback=self._dialogue_fallback(request),
        )
        self._audit(
            tenant_id=request.tenant_id,
            resource_id=request.session_id,
            task="dialogue.next_question",
            result=result,
        )
        return result

    async def generate_summary(self, request: ClinicalSummaryRequest) -> ClinicalSummaryResponse:
        payload = request.model_dump(mode="json")
        result = await self._validated_generate(
            task="summary.generate",
            payload=payload,
            response_model=ClinicalSummaryResponse,
            fallback=self._summary_fallback(request),
        )
        self._audit(
            tenant_id=request.tenant_id,
            resource_id=request.encounter_id,
            task="summary.generate",
            result=result,
        )
        return result

    async def _validated_generate(
        self,
        *,
        task: str,
        payload: dict[str, Any],
        response_model: type[ResponseT],
        fallback: dict[str, Any],
    ) -> ResponseT:
        for _attempt in range(self.max_attempts):
            try:
                raw = await self.provider.generate(task, payload)
                return response_model.model_validate(raw)
            except (ValidationError, TypeError, ValueError):
                continue
        return response_model.model_validate(fallback)

    def _audit(
        self,
        *,
        tenant_id: UUID,
        resource_id: UUID,
        task: str,
        result: BaseModel,
    ) -> None:
        # Do not write prompts, transcript text, answers, or generated clinical
        # content to this metadata. Durable PHI-safe audit storage is a release gate.
        audit_emitter.emit(
            tenant_id=tenant_id,
            actor_id=None,
            actor_type="system",
            actor_role="clinical_ai_router",
            action="ai_generate",
            resource_type="intake_session" if task.startswith("dialogue") else "encounter",
            resource_id=resource_id,
            purpose="clinical_intake_draft",
            audit_metadata={
                "task": task,
                "provider": self.provider.name,
                "schema_version": getattr(result, "schema_version", "unknown"),
                "degraded": getattr(result, "degraded", False),
            },
        )

    def _dialogue_fallback(self, request: DialogueRequest) -> dict[str, Any]:
        question = (
            "The question service is unavailable. Please continue using the touch form."
            if request.language == "en"
            else "प्रश्न सेवा उपलब्ध नहीं है। कृपया टच फ़ॉर्म से जानकारी भरें।"
        )
        return {
            "question": question,
            "answer_type": "review",
            "next_domain": "manual_entry",
            "confidence": {
                "score": 0.0,
                "basis": "template_fallback",
                "not_clinical_probability": True,
            },
            "evidence": [],
            "provider": "template-fallback",
            "degraded": True,
        }

    def _summary_fallback(self, request: ClinicalSummaryRequest) -> dict[str, Any]:
        warning_text = " ".join(
            [
                request.chief_complaint,
                request.transcript,
                *(str(value)[:500] for value in request.confirmed_answers.values()),
            ]
        )
        return {
            "chief_complaint": request.chief_complaint,
            "history_of_present_illness": ["Structured intake is available for manual review."],
            "relevant_negatives": [],
            "document_facts": request.document_facts,
            "red_flags": detect_red_flags(warning_text),
            "uncertainties": ["Automated summary generation was unavailable."],
            "confidence": {
                "score": 0.0,
                "basis": "template_fallback",
                "not_clinical_probability": True,
            },
            "evidence": [
                {
                    "output_path": "chief_complaint",
                    "source_path": "chief_complaint",
                    "source_type": "patient_response",
                },
                *[
                    {
                        "output_path": f"document_facts[{index}]",
                        "source_path": (
                            request.document_fact_source_paths[index]
                            if index < len(request.document_fact_source_paths)
                            else f"document_facts[{index}]"
                        ),
                        "source_type": "document",
                    }
                    for index, _ in enumerate(request.document_facts)
                ],
            ],
            "clinician_review_required": True,
            "provider": "template-fallback",
            "degraded": True,
        }


_router: LLMRouter | None = None


def get_llm_router() -> LLMRouter:
    global _router
    if _router is None:
        _router = LLMRouter(build_provider(settings.LLM_PROVIDER))
    return _router


def reset_llm_router() -> None:
    """Clear the singleton after configuration overrides in tests."""
    global _router
    _router = None
