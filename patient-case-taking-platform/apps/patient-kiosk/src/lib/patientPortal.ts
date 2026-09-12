import { clearPatientIdentity, currentPatientIdentity, patientAccessToken, patientClerkEnabled } from "./patientIdentity";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const DEMO_IDENTITY = {
  tenantId: "11111111-1111-4111-8111-111111111111",
  facilityId: "22222222-2222-4222-8222-222222222222",
  patientId: "33333333-3333-4333-8333-333333333333",
};

export interface PatientSession {
  accessToken: string;
  tenantId: string;
  facilityId: string;
  patientId: string;
}

export interface PatientReportListItem {
  id: string;
  encounter_id: string;
  facility_id: string;
  title: string;
  signed_at: string;
  signature_sha256: string;
  provider: "mock" | "template-fallback";
  degraded: boolean;
}

export interface PatientReportDetail extends PatientReportListItem {
  generation: number;
  schema_version: string;
  content: {
    chief_complaint: string;
    history_of_present_illness: string[];
    relevant_negatives: string[];
    document_facts: string[];
    red_flags: string[];
    uncertainties: string[];
  };
  evidence: Array<{
    output_path: string;
    source_path: string;
    source_type: string;
  }>;
}

export interface TimelineEntry {
  id: string;
  encounter_id: string;
  document_id: string;
  event_type: string;
  display_value: string;
  unit: string | null;
  statement_status: string;
  occurred_at: string;
}

export interface PatientLongitudinalEvent {
  record_id: string;
  facility_id: string;
  encounter_id: string;
  document_id: string | null;
  source_kind: "signed_summary" | "reviewed_fact";
  source_id: string;
  title: string;
  details: string[];
  entity_type: string | null;
  statement_status: string | null;
  occurred_at: string;
}

export interface PatientLongitudinalTimeline {
  patient_id: string;
  events: PatientLongitudinalEvent[];
  summary: {
    total_events: number;
    encounter_count: number;
    signed_summary_count: number;
    reviewed_fact_count: number;
    first_event_at: string | null;
    last_event_at: string | null;
  };
}

export interface PatientDashboard {
  patient_id: string;
  signed_report_count: number;
  reviewed_timeline_count: number;
  recent_reports: PatientReportListItem[];
  recent_timeline: TimelineEntry[];
}

export interface PatientDocument {
  id: string;
  tenant_id: string;
  facility_id: string;
  patient_id: string;
  encounter_id: string;
  purpose: string;
  declared_document_class: string;
  suggested_document_class: string | null;
  reviewed_document_class: string | null;
  declared_mime: string;
  declared_size_bytes: number;
  state: string;
  version: number;
  created_at: string;
  updated_at: string;
  upload_expires_at: string;
}

export interface PatientConsent {
  id: string;
  patient_id: string;
  encounter_id: string;
  purpose: string;
  scope: Record<string, unknown>;
  status: string;
  granted_at: string;
  expires_at: string | null;
  revoked_at: string | null;
  version: number;
}

const SESSION_KEY = "medikiosk-patient-session";

export function readPatientSession(): PatientSession | null {
  if (patientClerkEnabled) return currentPatientIdentity();
  const value = sessionStorage.getItem(SESSION_KEY);
  if (!value) return null;
  try {
    return JSON.parse(value) as PatientSession;
  } catch {
    sessionStorage.removeItem(SESSION_KEY);
    return null;
  }
}

export function clearPatientSession(): void {
  clearPatientIdentity();
  sessionStorage.removeItem(SESSION_KEY);
}

export async function createDemoPatientSession(
  identity = DEMO_IDENTITY,
): Promise<PatientSession> {
  if (patientClerkEnabled) throw new Error("Use patient sign-in to access this application.");
  const query = new URLSearchParams({
    user_id: identity.patientId,
    email: "synthetic.patient@example.test",
    role: "patient",
    tenant_id: identity.tenantId,
  });
  query.append("facility_ids", identity.facilityId);
  const response = await fetch(`${API_URL}/api/v1/auth/token?${query}`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error("Local patient access is unavailable. Enable demo routes for synthetic data.");
  }
  const payload = (await response.json()) as { token?: string };
  if (!payload.token) throw new Error("Patient access returned no token");
  const session = { accessToken: payload.token, ...identity };
  sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
  return session;
}

async function patientFetch(
  session: PatientSession,
  path: string,
  init?: RequestInit,
): Promise<Response> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      ...init?.headers,
      Authorization: `Bearer ${await patientAccessToken(session)}`,
    },
  });
  if (response.status === 401) {
    const current = readPatientSession();
    // A delayed failure from the previous patient must not clear the new session.
    if (current && (patientClerkEnabled ? current === session : current.accessToken === session.accessToken)) {
      clearPatientSession();
    }
  }
  return response;
}

async function patientJson<Response>(
  session: PatientSession,
  path: string,
): Promise<Response> {
  const response = await patientFetch(session, path);
  if (!response.ok) throw new Error(`Patient service failed (${response.status})`);
  return response.json() as Promise<Response>;
}

export function getPatientDashboard(session: PatientSession): Promise<PatientDashboard> {
  return patientJson(session, "/api/v1/patient-portal/me/dashboard");
}

export async function confirmPatientSafety(
  session: PatientSession,
  confirmation: {
    encounter_id: string;
    consent_id: string;
    input_version: number;
    chief_complaint: string;
    confirmed_answers: Record<string, string>;
  },
): Promise<{ interrupt_required: boolean; durable_alert_count: number; staff_acknowledged: false }> {
  const response = await patientFetch(session, "/api/v1/patient-portal/me/safety-confirmations", {
    method: "POST",
    signal: AbortSignal.timeout(15_000),
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...confirmation, facility_id: session.facilityId, confirmed: true }),
  });
  if (!response.ok) throw new Error(`Safety confirmation failed (${response.status})`);
  return response.json();
}

export function listPatientReports(
  session: PatientSession,
): Promise<PatientReportListItem[]> {
  return patientJson(session, "/api/v1/patient-portal/me/reports");
}

export function getPatientLongitudinalTimeline(
  session: PatientSession,
): Promise<PatientLongitudinalTimeline> {
  return patientJson(
    session,
    "/api/v1/patient-portal/me/longitudinal-timeline?purpose=treatment",
  );
}

export function getPatientReport(
  session: PatientSession,
  reportId: string,
): Promise<PatientReportDetail> {
  return patientJson(session, `/api/v1/patient-portal/me/reports/${reportId}`);
}

export async function downloadPatientReport(
  session: PatientSession,
  reportId: string,
): Promise<void> {
  const response = await patientFetch(
    session,
    `/api/v1/patient-portal/me/reports/${reportId}/download`,
  );
  if (!response.ok) throw new Error(`Report download failed (${response.status})`);
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `medikiosk-report-${reportId}.txt`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function listPatientDocuments(
  session: PatientSession,
): Promise<PatientDocument[]> {
  return patientJson(session, "/api/v1/patient-portal/me/documents");
}

export function getPatientDocument(
  session: PatientSession,
  documentId: string,
): Promise<PatientDocument> {
  return patientJson(session, `/api/v1/patient-portal/me/documents/${documentId}`);
}

export async function uploadPatientPrescription(
  session: PatientSession,
  file: File,
  encounterId: string,
  consentReference: string,
): Promise<PatientDocument> {
  const registered = await patientFetch(
    session,
    "/api/v1/patient-portal/me/documents",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": crypto.randomUUID(),
      },
      body: JSON.stringify({
        facility_id: session.facilityId,
        encounter_id: encounterId,
        consent_reference: consentReference,
        original_filename: file.name,
        declared_mime: file.type,
        declared_size_bytes: file.size,
      }),
    },
  );
  if (!registered.ok) throw new Error(await patientError(registered, "Registration failed"));
  const document = (await registered.json()) as PatientDocument;

  const grantResponse = await patientFetch(
    session,
    `/api/v1/patient-portal/me/documents/${document.id}/upload-session`,
    { method: "POST" },
  );
  if (!grantResponse.ok) throw new Error(await patientError(grantResponse, "Upload grant failed"));
  const grant = (await grantResponse.json()) as {
    url: string;
    required_headers: Record<string, string>;
  };
  const uploaded = await fetch(grant.url, {
    method: "PUT",
    headers: grant.required_headers,
    body: file,
  });
  if (!uploaded.ok) throw new Error(`Object upload failed (${uploaded.status})`);

  const finalized = await patientFetch(
    session,
    `/api/v1/patient-portal/me/documents/${document.id}/finalize`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_version: document.version }),
    },
  );
  if (!finalized.ok) throw new Error(await patientError(finalized, "Finalization failed"));
  return finalized.json() as Promise<PatientDocument>;
}

async function patientError(response: Response, fallback: string): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: string };
    return payload.detail || `${fallback} (${response.status})`;
  } catch {
    return `${fallback} (${response.status})`;
  }
}

export async function grantPatientConsent(
  session: PatientSession,
  encounterId: string,
  retainAudio: boolean,
): Promise<PatientConsent> {
  const response = await patientFetch(session, "/api/v1/patient-portal/me/consents", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      encounter_id: encounterId,
      document_upload: true,
      retain_audio: retainAudio,
      expires_in_hours: 24,
    }),
  });
  if (!response.ok) throw new Error(await patientError(response, "Consent could not be saved"));
  return response.json() as Promise<PatientConsent>;
}

export function listPatientConsents(session: PatientSession): Promise<PatientConsent[]> {
  return patientJson(session, "/api/v1/patient-portal/me/consents");
}

export async function revokePatientConsent(
  session: PatientSession,
  consentId: string,
): Promise<PatientConsent> {
  const response = await patientFetch(
    session,
    `/api/v1/patient-portal/me/consents/${consentId}/revoke`,
    { method: "POST" },
  );
  if (!response.ok) throw new Error(await patientError(response, "Consent could not be revoked"));
  return response.json() as Promise<PatientConsent>;
}

export async function submitPatientIntake(
  session: PatientSession,
  input: {
    encounterId: string;
    sessionId: string;
    consentId: string;
    language: "hi" | "en";
    chiefComplaint: string;
    confirmedAnswers: Record<string, string>;
    summaryDraft: {
      chief_complaint: string;
      history_of_present_illness: string[];
      relevant_negatives: string[];
      document_facts: string[];
      red_flags: string[];
      uncertainties: string[];
    };
    decision: "accepted" | "rejected";
    provider: "mock" | "template-fallback";
  },
): Promise<{ id: string; decision: string; created_at: string }> {
  const response = await patientFetch(session, "/api/v1/patient-portal/me/intakes", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": `patient-intake-${input.encounterId}`,
    },
    body: JSON.stringify({
      facility_id: session.facilityId,
      encounter_id: input.encounterId,
      session_id: input.sessionId,
      consent_id: input.consentId,
      language: input.language,
      chief_complaint: input.chiefComplaint,
      confirmed_answers: input.confirmedAnswers,
      summary_draft: input.summaryDraft,
      decision: input.decision,
      provider: input.provider,
    }),
  });
  if (!response.ok) throw new Error(await patientError(response, "Intake could not be saved"));
  return response.json() as Promise<{ id: string; decision: string; created_at: string }>;
}
