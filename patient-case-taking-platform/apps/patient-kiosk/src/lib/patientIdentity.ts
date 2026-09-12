import type { PatientSession } from "./patientPortal";

export const patientClerkEnabled = process.env.NEXT_PUBLIC_AUTH_PROVIDER === "clerk";
type TokenReader = () => Promise<string | null>;
let reader: TokenReader | null = null;
let active: PatientSession | null = null;
let generation = 0;

export function currentPatientIdentity(): PatientSession | null { return active; }

export function clearPatientIdentity(): void {
  generation += 1;
  active = null;
  reader = null;
  // These references must never carry over to the next patient on a shared kiosk.
  for (const key of ["notmid-kiosk-session-id", "notmid-encounter-id", "notmid-consent-id", "notmid-retain-audio"]) {
    localStorage.removeItem(key);
  }
}

export async function bindPatientIdentity(tokenReader: TokenReader, signal?: AbortSignal): Promise<() => void> {
  clearPatientIdentity();
  const version = generation;
  const token = await tokenReader();
  if (!token) throw new Error("Patient sign-in is required.");
  const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/v1/auth/me`, {
    cache: "no-store", signal, headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) throw new Error("Patient access could not be verified. Please retry or ask staff for help.");
  const identity = await response.json();
  const facilities: unknown = identity.facility_ids;
  if (identity.role !== "patient" || !Array.isArray(facilities) || !facilities.length || !facilities.every(value => typeof value === "string")) {
    throw new Error("An active patient and facility assignment is required.");
  }
  const facility = process.env.NEXT_PUBLIC_PATIENT_FACILITY_ID || (facilities.length === 1 ? facilities[0] : null);
  if (!facility || !facilities.includes(facility)) throw new Error("This kiosk needs a permitted facility configuration.");
  if (signal?.aborted || version !== generation) throw new Error("Patient session changed during verification.");
  // No provider credential is persisted; every use obtains a fresh SDK token.
  active = { patientId: identity.user_id, tenantId: identity.tenant_id, facilityId: facility, accessToken: "" };
  reader = tokenReader;
  return () => { if (version === generation) clearPatientIdentity(); };
}

export async function patientAccessToken(session: PatientSession): Promise<string> {
  if (!patientClerkEnabled) {
    if (!session.accessToken) throw new Error("Patient sign-in is required.");
    return session.accessToken;
  }
  const version = generation;
  if (!active || !reader || session !== active) throw new Error("Patient session changed. Start again.");
  const token = await reader();
  if (!token || version !== generation || session !== active) throw new Error("Patient session expired or changed. Sign in again.");
  return token;
}
