"""Anthropic Claude provider for clinical dialogue and summary tasks.

Model: claude-3-5-haiku-20241022 (default — fast, cost-effective)
       Override with ANTHROPIC_MODEL in .env.

Set in .env:
    LLM_PROVIDER=anthropic
    ANTHROPIC_API_KEY=sk-ant-...
    ANTHROPIC_MODEL=claude-3-5-haiku-20241022
    ANTHROPIC_MAX_TOKENS=1024
    ANTHROPIC_TIMEOUT_SECONDS=30.0

The provider uses the official `anthropic` Python SDK (async client).

IMPORTANT: All model output goes through the deterministic red-flag rules engine.
Clinician review is mandatory for all generated summaries. This provider makes
network calls to Anthropic's API — ensure ANTHROPIC_API_KEY is kept secret and
never committed to source control.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.config import settings
from app.llm.prompts import (
    DIALOGUE_SYSTEM_PROMPT,
    SUMMARY_SYSTEM_PROMPT,
)
from app.rules.triage import evaluate_text_sources

logger = logging.getLogger(__name__)

_PROVIDER_NAME = "anthropic"


class AnthropicClinicalProvider:
    """Anthropic Claude provider.

    Uses the async `anthropic` client. The client is created lazily so that
    import errors surface at call time rather than at startup when the provider
    is not configured.
    """

    name = _PROVIDER_NAME
    external_network_used = True

    def __init__(self) -> None:
        self._client: Any | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def health(self) -> bool:
        try:
            client = self._get_client()
            # Minimal API check — count tokens on a tiny string
            await client.messages.create(
                model=settings.ANTHROPIC_MODEL,
                max_tokens=10,
                messages=[{"role": "user", "content": "ping"}],
            )
            return True
        except Exception:
            logger.exception("Anthropic health check failed")
            return False

    async def generate(self, task: str, payload: dict[str, Any]) -> dict[str, Any]:
        if task == "dialogue.next_question":
            return await self._next_question(payload)
        if task == "summary.generate":
            return await self._summary(payload)
        raise ValueError(f"Unsupported LLM task for Anthropic: {task}")

    # ------------------------------------------------------------------
    # Client initialisation
    # ------------------------------------------------------------------

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        api_key = settings.ANTHROPIC_API_KEY
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Add it to .env to use the Anthropic provider."
            )
        try:
            import anthropic  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "anthropic SDK is not installed. Run: pip install anthropic==0.40.0"
            ) from exc
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key,
            timeout=settings.ANTHROPIC_TIMEOUT_SECONDS,
        )
        return self._client

    # ------------------------------------------------------------------
    # Task implementations
    # ------------------------------------------------------------------

    async def _next_question(self, payload: dict[str, Any]) -> dict[str, Any]:
        language = payload.get("language", "hi")
        chief_complaint = payload.get("chief_complaint", "")
        last_message = payload.get("last_patient_message", "")
        collected = payload.get("collected_answers", {})

        # Deterministic red-flag check always runs first, regardless of provider
        text_sources = {
            "chief_complaint": chief_complaint,
            "last_patient_message": last_message,
            **{f"collected_answers.{k}": str(v)[:500] for k, v in collected.items()},
        }
        evaluation = evaluate_text_sources(text_sources)
        if evaluation.flags:
            flags = [f.rule_id for f in evaluation.flags]
            question = (
                "I may have heard a warning symptom. Please alert a staff member now. "
                "Are you able to breathe and stay conscious?"
                if language == "en"
                else "आपके बताए लक्षण में खतरे का संकेत हो सकता है। अभी स्टाफ को बुलाइए। "
                "क्या आप सांस ले पा रहे हैं और होश में हैं?"
            )
            return {
                "question": question,
                "answer_type": "urgent_action",
                "next_domain": "red_flags",
                "options": [],
                "safety_flags": flags,
                "escalation_required": True,
                "confidence": {
                    "score": 1.0,
                    "basis": "deterministic_rule",
                    "not_clinical_probability": True,
                },
                "evidence": [],
                "provider": _PROVIDER_NAME,
            }

        system = DIALOGUE_SYSTEM_PROMPT.format(
            language="Hindi" if language == "hi" else "English",
            provider_name=_PROVIDER_NAME,
        )
        answered_domains = [k for k, v in collected.items() if v not in (None, "", [], {})]
        user_content = (
            f"Chief complaint: {chief_complaint}\n"
            f"Last patient message: {last_message}\n"
            f"Already answered SOCRATES domains: {', '.join(answered_domains) or 'none'}\n"
            "Produce the next question JSON."
        )

        raw = await self._complete(system=system, user=user_content)
        result = _parse_json(raw)
        result.setdefault("provider", _PROVIDER_NAME)
        result.setdefault("safety_flags", [])
        result.setdefault("escalation_required", False)
        result.setdefault("options", [])
        result.setdefault("evidence", [])
        result["confidence"] = {
            "score": float(result.get("confidence", {}).get("score", 0.85)),
            "basis": "structured_completeness",
            "not_clinical_probability": True,
        }
        return result

    async def _summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        chief_complaint = payload.get("chief_complaint", "")
        confirmed = payload.get("confirmed_answers", {})
        transcript = payload.get("transcript", "")
        document_facts = payload.get("document_facts", [])
        document_fact_source_paths = payload.get("document_fact_source_paths", [])

        system = SUMMARY_SYSTEM_PROMPT.format(provider_name=_PROVIDER_NAME)
        user_content = (
            f"chief_complaint: {chief_complaint}\n"
            f"confirmed_answers: {json.dumps(confirmed, ensure_ascii=False)}\n"
            f"transcript (max 2000 chars): {transcript[:2000]}\n"
            f"document_facts: {json.dumps(document_facts[:20], ensure_ascii=False)}\n"
            "Produce the summary JSON."
        )

        raw = await self._complete(system=system, user=user_content)
        result = _parse_json(raw)

        # Always recompute red flags deterministically
        answers_for_rules = {
            "chief_complaint": chief_complaint,
            "symptoms": [v for v in confirmed.values() if isinstance(v, str) and v.strip()],
            **confirmed,
        }
        text_sources_for_rules = {
            "chief_complaint": chief_complaint,
            "transcript": transcript,
            **{f"confirmed_answers.{k}": str(v)[:500] for k, v in confirmed.items()},
        }
        from app.rules.engine import engine as rules_engine
        all_results = rules_engine.evaluate(answers_for_rules, {"text_sources": text_sources_for_rules})
        result["red_flags"] = [r.rule_id for r in all_results]
        result["clinician_review_required"] = True
        result["provider"] = _PROVIDER_NAME

        # Ground document_facts in the verified input
        result["document_facts"] = [str(f)[:500] for f in document_facts]

        doc_evidence = [
            {
                "output_path": f"document_facts[{i}]",
                "source_path": (
                    document_fact_source_paths[i]
                    if i < len(document_fact_source_paths)
                    else f"document_facts[{i}]"
                ),
                "source_type": "document",
            }
            for i in range(len(document_facts))
        ]
        existing_evidence = result.get("evidence", [])
        result["evidence"] = existing_evidence + doc_evidence

        result["confidence"] = {
            "score": float(result.get("confidence", {}).get("score", 0.85)),
            "basis": "structured_completeness",
            "not_clinical_probability": True,
        }
        return result

    # ------------------------------------------------------------------
    # Low-level completion
    # ------------------------------------------------------------------

    async def _complete(self, *, system: str, user: str) -> str:
        """Call the Anthropic messages API and return the text content."""
        client = self._get_client()
        response = await client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=settings.ANTHROPIC_MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return response.content[0].text.strip()


# ---------------------------------------------------------------------------
# JSON parsing helper (shared pattern with MedGemma provider)
# ---------------------------------------------------------------------------

def _parse_json(raw: str) -> dict[str, Any]:
    """Extract the first JSON object from a model response."""
    raw = re.sub(r"```(?:json)?\s*", "", raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*?\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    logger.warning("Anthropic returned non-JSON output: %s", raw[:200])
    raise ValueError(f"Anthropic response could not be parsed as JSON: {raw[:200]}")
