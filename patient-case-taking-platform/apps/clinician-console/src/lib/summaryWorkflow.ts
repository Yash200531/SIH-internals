import { clinicalAccessToken } from "./clinicalSession";

export type SummaryStatus = "draft" | "in_review" | "rejected" | "signed" | "superseded";

export type SummaryContent = {
  chief_complaint: string;
  history_of_present_illness: string[];
  relevant_negatives: string[];
  document_facts: string[];
  red_flags: string[];
  uncertainties: string[];
};

export type EvidenceLink = {
  output_path: string;
  source_path: string;
  source_type: "patient_response" | "document" | "deterministic_rule";
};

export type SummaryRecord = {
  id: string;
  tenant_id: string;
  facility_id: string;
  patient_id: string;
  encounter_id: string;
  lineage_id: string;
  generation: number;
  parent_summary_id: string | null;
  status: SummaryStatus;
  content: SummaryContent;
  evidence: EvidenceLink[];
  confidence: { score: number; basis: string; not_clinical_probability: true };
  provider: "mock" | "template-fallback";
  degraded: boolean;
  lock_version: number;
  updated_at: string;
  signature_sha256: string | null;
  rejection_reason: string | null;
};

export class SummaryApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";


async function request<T>(path: string, init?: RequestInit, resource = "summary-workflows"): Promise<T> {
  const response = await fetch(`${apiUrl}/api/v1/${resource}${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      Authorization: `Bearer ${await clinicalAccessToken()}`,
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new SummaryApiError(
      payload?.detail ?? "The clinical summary service is unavailable.",
      response.status,
    );
  }
  return (await response.json()) as T;
}

export function listSummaries(encounterId: string): Promise<SummaryRecord[]> {
  return request(`?encounter_id=${encodeURIComponent(encounterId)}`);
}

export type IntakeHandoff = {
  id: string; facility_id: string; patient_id: string; encounter_id: string;
  language: "en" | "hi"; chief_complaint: string; confirmed_answers: Record<string, string>;
  created_at: string; context_version: number | null;
};

export function listIntakes(offset = 0): Promise<IntakeHandoff[]> {
  return request(`?purpose=treatment&limit=50&offset=${offset}`, undefined, "intake-worklist");
}

export function confirmIntake(intake: IntakeHandoff): Promise<{ version: number }> {
  return request(`/${intake.id}/confirm`, {
    method: "POST", body: JSON.stringify({ reviewed: true, expected_version: intake.context_version }),
  }, "intake-worklist");
}

export function generateIntakeSummary(intake: IntakeHandoff): Promise<SummaryRecord> {
  return request("/generate", {
    method: "POST", headers: { "Idempotency-Key": `intake-handoff-${intake.id}` },
    body: JSON.stringify({ facility_id: intake.facility_id, patient_id: intake.patient_id,
      encounter_id: intake.encounter_id, language: intake.language }),
  });
}

export function saveDraft(summary: SummaryRecord, content: SummaryContent) {
  return request<SummaryRecord>(`/${summary.id}/draft`, {
    method: "PATCH",
    body: JSON.stringify({ expected_version: summary.lock_version, content }),
  });
}

export function submitForReview(summary: SummaryRecord) {
  return request<SummaryRecord>(`/${summary.id}/submit-review`, {
    method: "POST",
    body: JSON.stringify({ expected_version: summary.lock_version }),
  });
}

export function rejectSummary(summary: SummaryRecord, reason: string) {
  return request<SummaryRecord>(`/${summary.id}/reject`, {
    method: "POST",
    body: JSON.stringify({ expected_version: summary.lock_version, reason }),
  });
}

export function regenerateSummary(summary: SummaryRecord) {
  return request<SummaryRecord>(`/${summary.id}/regenerate`, {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify({
      facility_id: summary.facility_id,
      patient_id: summary.patient_id,
      encounter_id: summary.encounter_id,
      language: "en",
      expected_version: summary.lock_version,
    }),
  });
}

export function signSummary(summary: SummaryRecord) {
  return request<SummaryRecord>(`/${summary.id}/sign`, {
    method: "POST",
    body: JSON.stringify({ expected_version: summary.lock_version }),
  });
}

export type ClinicalAlert = {
  delivery: "pending" | "failed" | "broker_published";
  lifecycle: { id: string; encounter_id: string; version: number; state: "open" | "acknowledged" | "escalated" | "resolved" | "overridden"; owner_role: string; owner_actor_id: string | null; updated_at: string };
  rule: { rule_id: string; severity: string; explanation_code: string; evidence_paths: string[]; approval_status: string };
};

export function listAlerts(includeClosed = false): Promise<ClinicalAlert[]> {
  return request(`?purpose=treatment&include_closed=${includeClosed}`, undefined, "alerts");
}
export function evaluateIntakeAlerts(intakeId: string): Promise<{ outcome: string; alerts: unknown[] }> {
  return request(`/from-intake/${encodeURIComponent(intakeId)}?purpose=treatment`, {
    method: "POST", body: JSON.stringify({ reviewed: true }),
  }, "alerts");
}
export function commandAlert(alert: ClinicalAlert, action: "acknowledge" | "resolve", rationale?: string): Promise<ClinicalAlert["lifecycle"]> {
  return request(`/${alert.lifecycle.id}/commands?purpose=treatment`, {
    method: "POST", headers: { "Idempotency-Key": `${alert.lifecycle.id}-${alert.lifecycle.version}-${action}` },
    body: JSON.stringify({ action, expected_version: alert.lifecycle.version,
      ...(action === "resolve" ? { reason_code: "clinician_assessed", rationale } : {}) }),
  }, "alerts");
}
