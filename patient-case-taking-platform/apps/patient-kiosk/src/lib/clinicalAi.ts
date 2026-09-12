export type Language = "hi" | "en";

export interface DialogueResponse {
  question: string;
  answer_type: "free_text" | "single_choice" | "number" | "review" | "urgent_action";
  next_domain: string;
  options: string[];
  safety_flags: string[];
  escalation_required: boolean;
  provider: string;
  degraded: boolean;
}

export interface ClinicalSummaryResponse {
  chief_complaint: string;
  history_of_present_illness: string[];
  relevant_negatives: string[];
  document_facts: string[];
  red_flags: string[];
  uncertainties: string[];
  clinician_review_required: true;
  provider: string;
  degraded: boolean;
}

interface DialogueInput {
  tenantId: string;
  sessionId: string;
  language: Language;
  chiefComplaint: string;
  lastPatientMessage: string;
  collectedAnswers: Record<string, string>;
}

interface SummaryInput {
  tenantId: string;
  encounterId: string;
  language: Language;
  chiefComplaint: string;
  confirmedAnswers: Record<string, string>;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function postJson<Response>(path: string, body: unknown): Promise<Response> {
  const response = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    throw new Error(`Assistant service unavailable (${response.status})`);
  }

  return response.json() as Promise<Response>;
}

export function getNextQuestion(input: DialogueInput): Promise<DialogueResponse> {
  return postJson("/api/v1/clinical-ai/dialogue/next", {
    tenant_id: input.tenantId,
    session_id: input.sessionId,
    language: input.language,
    chief_complaint: input.chiefComplaint,
    last_patient_message: input.lastPatientMessage,
    collected_answers: input.collectedAnswers,
  });
}

export function generateClinicalSummary(
  input: SummaryInput,
): Promise<ClinicalSummaryResponse> {
  return postJson("/api/v1/clinical-ai/summaries/generate", {
    tenant_id: input.tenantId,
    encounter_id: input.encounterId,
    language: input.language,
    chief_complaint: input.chiefComplaint,
    confirmed_answers: input.confirmedAnswers,
    transcript: "",
    document_facts: [],
  });
}
