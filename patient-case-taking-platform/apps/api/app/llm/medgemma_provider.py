"""MedGemma 4B-IT local inference provider via llama-cpp-python (GGUF).

Model: google/medgemma-4b-it (Q4_K_M GGUF, ~3.0 GB, fits in 6 GB VRAM)
Download the GGUF from: https://huggingface.co/bartowski/google_medgemma-4b-it-GGUF
Recommended file: medgemma-4b-it-Q4_K_M.gguf

Set in .env:
    LLM_PROVIDER=medgemma
    MEDGEMMA_MODEL_PATH=/absolute/path/to/medgemma-4b-it-Q4_K_M.gguf
    MEDGEMMA_N_GPU_LAYERS=-1        # -1 offloads all layers to GPU (RTX 4050)
    MEDGEMMA_N_CTX=4096
    MEDGEMMA_MAX_TOKENS=512
    MEDGEMMA_TEMPERATURE=0.1

The provider loads the model lazily on first call so the API starts fast.
Inference runs in a thread pool to avoid blocking the async event loop.

IMPORTANT: This provider generates text using a locally running model.
All output must go through the deterministic red-flag rules engine before
being shown to a patient. Clinician review is mandatory for all summaries.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
from typing import Any

from app.config import settings
from app.llm.prompts import (
    DIALOGUE_SYSTEM_PROMPT,
    SUMMARY_SYSTEM_PROMPT,
)
from app.rules.triage import evaluate_text_sources

logger = logging.getLogger(__name__)

_PROVIDER_NAME = "medgemma"


class MedGemmaProvider:
    """Local MedGemma 4B-IT inference via llama-cpp-python.

    Thread-safe: a single threading.Lock serialises inference calls so the
    model's KV cache is not corrupted by concurrent requests.
    """

    name = _PROVIDER_NAME
    external_network_used = False

    def __init__(self) -> None:
        self._model: Any | None = None
        self._load_lock = threading.Lock()
        self._inference_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def health(self) -> bool:
        try:
            await asyncio.to_thread(self._ensure_model)
            return True
        except Exception:
            logger.exception("MedGemma health check failed")
            return False

    async def generate(self, task: str, payload: dict[str, Any]) -> dict[str, Any]:
        if task == "dialogue.next_question":
            return await asyncio.to_thread(self._sync_next_question, payload)
        if task == "summary.generate":
            return await asyncio.to_thread(self._sync_summary, payload)
        raise ValueError(f"Unsupported LLM task for MedGemma: {task}")

    # ------------------------------------------------------------------
    # Lazy model loading
    # ------------------------------------------------------------------

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            model_path = settings.MEDGEMMA_MODEL_PATH
            if not model_path:
                raise RuntimeError(
                    "MEDGEMMA_MODEL_PATH is not set. "
                    "Download medgemma-4b-it-Q4_K_M.gguf and set the path in .env"
                )
            try:
                from llama_cpp import Llama  # type: ignore[import]
            except ImportError as exc:
                raise RuntimeError(
                    "llama-cpp-python is not installed. "
                    "Run: pip install llama-cpp-python --extra-index-url "
                    "https://abetlen.github.io/llama-cpp-python/whl/cu124"
                ) from exc

            logger.info("Loading MedGemma model from %s ...", model_path)
            self._model = Llama(
                model_path=model_path,
                n_gpu_layers=settings.MEDGEMMA_N_GPU_LAYERS,
                n_ctx=settings.MEDGEMMA_N_CTX,
                verbose=False,
                chat_format="gemma",
            )
            logger.info(
                "MedGemma loaded (n_gpu_layers=%d, n_ctx=%d)",
                settings.MEDGEMMA_N_GPU_LAYERS,
                settings.MEDGEMMA_N_CTX,
            )

    # ------------------------------------------------------------------
    # Task implementations (run in thread pool)
    # ------------------------------------------------------------------

    def _sync_next_question(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_model()
        language = payload.get("language", "hi")
        chief_complaint = payload.get("chief_complaint", "")
        last_message = payload.get("last_patient_message", "")
        collected = payload.get("collected_answers", {})

        # Always run deterministic red-flag check first — never skip this
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
            f"Already answered SOCRATES domains: {', '.join(answered_domains) or 'none'}\n\n"
            f"Language for the question: {'Hindi' if language == 'hi' else 'English'}\n\n"
            "Return ONLY a JSON object with these exact keys:\n"
            '{"question": "<next question>", "answer_type": "<free_text|number|review>", '
            '"next_domain": "<socrates domain>", "options": [], "safety_flags": [], '
            '"escalation_required": false, '
            '"confidence": {"score": 0.85, "basis": "structured_completeness", "not_clinical_probability": true}, '
            '"evidence": [], "provider": "medgemma"}'
        )

        raw = self._chat([
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ])
        result = _parse_json(raw)
        result.setdefault("provider", _PROVIDER_NAME)
        result.setdefault("safety_flags", [])
        result.setdefault("escalation_required", False)
        result.setdefault("options", [])
        result.setdefault("evidence", [])
        # Enforce confidence schema
        result["confidence"] = {
            "score": float(result.get("confidence", {}).get("score", 0.8)),
            "basis": "structured_completeness",
            "not_clinical_probability": True,
        }
        return result

    def _sync_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_model()
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
            f"document_facts: {json.dumps(document_facts[:20], ensure_ascii=False)}\n\n"
            "Return ONLY a JSON object with these exact keys:\n"
            '{"chief_complaint": "<text>", "history_of_present_illness": ["<sentence>"], '
            '"relevant_negatives": [], "document_facts": [], "red_flags": [], '
            '"uncertainties": [], '
            '"confidence": {"score": 0.75, "basis": "structured_completeness", "not_clinical_probability": true}, '
            '"evidence": [], "clinician_review_required": true, "provider": "medgemma"}'
        )

        raw = self._chat([
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ])
        result = _parse_json(raw)

        # Always recompute red flags deterministically — never trust model output for safety
        # Build answers dict that matches what the rules engine expects
        answers_for_rules = {
            "chief_complaint": chief_complaint,
            "symptoms": [
                v for v in confirmed.values()
                if isinstance(v, str) and v.strip()
            ],
            **confirmed,
        }
        text_sources_for_rules = {
            "chief_complaint": chief_complaint,
            "transcript": transcript,
            **{f"confirmed_answers.{k}": str(v)[:500] for k, v in confirmed.items()},
        }
        from app.rules.engine import engine as rules_engine
        all_results = rules_engine.evaluate(answers_for_rules, {"text_sources": text_sources_for_rules})
        all_flag_ids = [r.rule_id for r in all_results]
        result["red_flags"] = all_flag_ids
        result["clinician_review_required"] = True
        result["provider"] = _PROVIDER_NAME

        # Ensure document_facts come from input, not hallucinated
        result["document_facts"] = [str(f)[:500] for f in document_facts]

        # Inject evidence links for document facts
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

        # Enforce confidence schema
        result["confidence"] = {
            "score": float(result.get("confidence", {}).get("score", 0.75)),
            "basis": "structured_completeness",
            "not_clinical_probability": True,
        }
        return result

    # ------------------------------------------------------------------
    # Low-level chat completion
    # ------------------------------------------------------------------

    def _chat(self, messages: list[dict[str, str]]) -> str:
        """Run a chat completion and return the raw text response."""
        model = self._model
        if model is None:
            raise RuntimeError("MedGemma model is not initialised")

        with self._inference_lock:
            response = model.create_chat_completion(
                messages=messages,
                max_tokens=settings.MEDGEMMA_MAX_TOKENS,
                temperature=settings.MEDGEMMA_TEMPERATURE,
                # No stop tokens — Gemma opens with ```json which would
                # prematurely fire a "```" stop token before any content.
            )
        return response["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# JSON parsing helper
# ---------------------------------------------------------------------------

def _parse_json(raw: str) -> dict[str, Any]:
    """Extract the first JSON object from a MedGemma response.

    MedGemma consistently wraps JSON in ```json ... ``` fences.
    This strips them and extracts the first valid JSON object.
    """
    # Strip markdown fences (```json ... ``` or ``` ... ```)
    raw = re.sub(r"```(?:json)?\s*", "", raw).strip()

    # Try direct parse first
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Find first {...} block (handles trailing prose after JSON)
    match = re.search(r"\{.*?\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # Try largest {...} block in case nested JSON
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    logger.warning("MedGemma returned non-JSON output: %s", raw[:200])
    raise ValueError(f"MedGemma response could not be parsed as JSON: {raw[:200]}")
