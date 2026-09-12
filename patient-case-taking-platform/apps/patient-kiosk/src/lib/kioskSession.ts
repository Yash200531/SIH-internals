import { createDemoPatientSession, readPatientSession } from "./patientPortal";
import { patientAccessToken, patientClerkEnabled } from "./patientIdentity";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface KioskSession {
  sessionId: string;
  encounterId: string;
  language: "hi" | "en";
}

export async function startLocalKioskSession(
  language: "hi" | "en",
): Promise<KioskSession> {
  const patient = patientClerkEnabled ? readPatientSession() : await createDemoPatientSession();
  if (!patient) throw new Error("Patient sign-in is required before starting an intake.");
  const response = await fetch(`${API_URL}/api/v1/patient-portal/me/sessions`, {
    method: "POST",
    cache: "no-store",
    headers: { Authorization: `Bearer ${await patientAccessToken(patient)}`,
      "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify({ facility_id: patient.facilityId, language }),
  });
  if (!response.ok) {
    throw new Error("Patient intake session is unavailable. Please retry or ask staff for help.");
  }
  const payload = (await response.json()) as { id?: string; encounter_id?: string };
  if (!payload.id || !payload.encounter_id) throw new Error("Patient session returned incomplete identifiers");
  const session = {
    sessionId: payload.id,
    encounterId: payload.encounter_id,
    language,
  };
  localStorage.setItem("notmid-kiosk-session-id", session.sessionId);
  localStorage.setItem("notmid-encounter-id", session.encounterId);
  localStorage.setItem("notmid-language", language);
  return session;
}
