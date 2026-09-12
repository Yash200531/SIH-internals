"""Provider boundary and deterministic mock implementation."""

from typing import Any, Protocol

from app.llm.ontology import SOCRATES_DOMAINS, SOCRATES_QUESTIONS
from app.rules.triage import detect_red_flags, evaluate_text_sources


class LLMProvider(Protocol):
    name: str
    external_network_used: bool

    async def generate(self, task: str, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def health(self) -> bool: ...


class MockClinicalProvider:
    """Offline provider for development, contracts, and deterministic demos.

    It deliberately performs no generative inference and makes no network call.
    Responses are produced from the versioned ontology and confirmed input only.
    """

    name = "mock"
    external_network_used = False

    async def health(self) -> bool:
        return True

    async def generate(self, task: str, payload: dict[str, Any]) -> dict[str, Any]:
        if task == "dialogue.next_question":
            return self._next_question(payload)
        if task == "summary.generate":
            return self._summary(payload)
        raise ValueError(f"Unsupported LLM task: {task}")

    def _next_question(self, payload: dict[str, Any]) -> dict[str, Any]:
        language = payload["language"]
        text_sources = {
            "chief_complaint": payload["chief_complaint"],
            "last_patient_message": payload["last_patient_message"],
            **{
                f"collected_answers.{key}": _flatten_text(value)
                for key, value in payload["collected_answers"].items()
            },
        }
        evaluation = evaluate_text_sources(text_sources)
        red_flags = [flag.rule_id for flag in evaluation.flags]
        if red_flags:
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
                "safety_flags": red_flags,
                "escalation_required": True,
                "confidence": {
                    "score": 1.0,
                    "basis": "deterministic_rule",
                    "not_clinical_probability": True,
                },
                "evidence": _red_flag_evidence(text_sources, red_flags),
                "provider": self.name,
            }

        answers = payload["collected_answers"]
        for domain in SOCRATES_DOMAINS:
            if not _has_meaningful_answer(answers.get(domain)):
                return {
                    "question": SOCRATES_QUESTIONS[language][domain],
                    "answer_type": "number" if domain == "severity" else "free_text",
                    "next_domain": domain,
                    "options": [],
                    "safety_flags": [],
                    "escalation_required": False,
                    "confidence": {
                        "score": 1.0,
                        "basis": "deterministic_rule",
                        "not_clinical_probability": True,
                    },
                    "evidence": [
                        {
                            "output_path": "next_domain",
                            "source_path": f"ontology.socrates.{domain}",
                            "source_type": "deterministic_rule",
                        }
                    ],
                    "provider": self.name,
                }

        review = (
            "Thank you. Please review your answers before sending them to the doctor."
            if language == "en"
            else "धन्यवाद। डॉक्टर को भेजने से पहले अपने उत्तर देख और सुधार लें।"
        )
        return {
            "question": review,
            "answer_type": "review",
            "next_domain": "review",
            "options": [],
            "safety_flags": [],
            "escalation_required": False,
            "confidence": {
                "score": 1.0,
                "basis": "structured_completeness",
                "not_clinical_probability": True,
            },
            "evidence": [
                {
                    "output_path": "next_domain",
                    "source_path": "collected_answers",
                    "source_type": "patient_response",
                }
            ],
            "provider": self.name,
        }

    def _summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        answers = payload["confirmed_answers"]
        complaint = payload["chief_complaint"].strip()
        transcript = payload["transcript"]
        # Use engine.evaluate() directly so RF-001 (chest pain + radiation) fires correctly
        from app.rules.engine import engine as rules_engine
        answers_for_rules = {
            "chief_complaint": complaint,
            "symptoms": [v for v in answers.values() if isinstance(v, str) and v.strip()],
            **answers,
        }
        text_sources_for_rules = {
            "chief_complaint": complaint,
            "transcript": transcript,
            **{f"confirmed_answers.{k}": str(v)[:500] for k, v in answers.items()},
        }
        all_results = rules_engine.evaluate(answers_for_rules, {"text_sources": text_sources_for_rules})
        red_flags = [r.rule_id for r in all_results]
        history_items = [
            (key, f"{key.replace('_', ' ').capitalize()}: {_safe_text(value)}")
            for key, value in answers.items()
            if _has_meaningful_answer(value) and not key.startswith("negative_")
        ]
        history = [item for _, item in history_items]
        negatives = [
            key.removeprefix("negative_").replace("_", " ")
            for key, value in answers.items()
            if key.startswith("negative_") and value is True
        ]
        uncertainties = []
        missing = [
            domain for domain in SOCRATES_DOMAINS if not _has_meaningful_answer(answers.get(domain))
        ]
        if missing:
            uncertainties.append("Missing fields: " + ", ".join(missing))
        if not history:
            history.append("No structured history has been confirmed yet.")
        completed = sum(_has_meaningful_answer(answers.get(domain)) for domain in SOCRATES_DOMAINS)
        evidence = [
            {
                "output_path": "chief_complaint",
                "source_path": "chief_complaint",
                "source_type": "patient_response",
            }
        ]
        evidence.extend(
            {
                "output_path": f"history_of_present_illness[{index}]",
                "source_path": f"confirmed_answers.{key}",
                "source_type": "patient_response",
            }
            for index, (key, _) in enumerate(history_items)
        )
        evidence.extend(
            {
                "output_path": f"relevant_negatives[{index}]",
                "source_path": f"confirmed_answers.negative_{item.replace(' ', '_')}",
                "source_type": "patient_response",
            }
            for index, item in enumerate(negatives)
        )
        evidence.extend(
            {
                "output_path": f"document_facts[{index}]",
                "source_path": (
                    payload["document_fact_source_paths"][index]
                    if index < len(payload["document_fact_source_paths"])
                    else f"document_facts[{index}]"
                ),
                "source_type": "document",
            }
            for index, _ in enumerate(payload["document_facts"])
        )
        return {
            "chief_complaint": complaint,
            "history_of_present_illness": history,
            "relevant_negatives": negatives,
            "document_facts": [str(item)[:500] for item in payload["document_facts"]],
            "red_flags": red_flags,
            "uncertainties": uncertainties,
            "confidence": {
                "score": completed / len(SOCRATES_DOMAINS),
                "basis": "structured_completeness",
                "not_clinical_probability": True,
            },
            "evidence": evidence,
            "clinician_review_required": True,
            "provider": self.name,
        }


def _has_meaningful_answer(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def _safe_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()[:500]
    return str(value)[:500]


def _flatten_text(value: Any) -> str:
    """Flatten bounded request data for deterministic warning-term matching."""
    if isinstance(value, dict):
        return " ".join(_flatten_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_flatten_text(item) for item in value)
    return _safe_text(value)


def _red_flag_evidence(sources: dict[str, str], flags: list[str]) -> list[dict[str, str]]:
    evidence: list[dict[str, str]] = []
    for source_path, source_text in sources.items():
        matched = set(detect_red_flags(source_text))
        for flag in flags:
            if flag in matched:
                evidence.append(
                    {
                        "output_path": f"safety_flags.{flag}",
                        "source_path": source_path,
                        "source_type": "patient_response",
                    }
                )
    return evidence


def build_provider(provider_name: str) -> LLMProvider:
    if provider_name == "mock":
        return MockClinicalProvider()
    if provider_name == "medgemma":
        from app.llm.medgemma_provider import MedGemmaProvider
        return MedGemmaProvider()
    if provider_name == "anthropic":
        from app.llm.anthropic_provider import AnthropicClinicalProvider
        return AnthropicClinicalProvider()
    raise RuntimeError(
        f"LLM provider '{provider_name}' is not available. "
        "Supported providers: mock, medgemma, anthropic"
    )
