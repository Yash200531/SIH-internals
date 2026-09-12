/** Credentials stay with their provider; internal role comes from the API. */
export const clerkEnabled = process.env.NEXT_PUBLIC_AUTH_PROVIDER === "clerk";
const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
type TokenReader = () => Promise<string | null>;
let tokenReader: TokenReader | null = null;
let role: "doctor" | "nurse" | null = null;

export class ClinicalSessionError extends Error {
  constructor(message: string, readonly status = 401) { super(message); }
}

export function bindClinicalTokenReader(reader: TokenReader): () => void {
  tokenReader = reader;
  return () => { if (tokenReader === reader) { tokenReader = null; role = null; } };
}

export async function clinicalAccessToken(): Promise<string> {
  const token = clerkEnabled
    ? await tokenReader?.()
    : window.sessionStorage.getItem("medikiosk.access_token");
  if (!token) throw new ClinicalSessionError("Clinical session unavailable. Sign in again.");
  return token;
}

export function clinicalRole(): "doctor" | "nurse" | null {
  if (clerkEnabled) return role;
  if (typeof window === "undefined") return null;
  const stored = window.sessionStorage.getItem("medikiosk.clinician_role");
  return stored === "doctor" || stored === "nurse" ? stored : null;
}

export async function verifyClinicalSession(signal?: AbortSignal): Promise<void> {
  const response = await fetch(`${apiUrl}/api/v1/auth/me`, {
    cache: "no-store", signal, headers: { Authorization: `Bearer ${await clinicalAccessToken()}` },
  });
  if (!response.ok) throw new ClinicalSessionError(
    response.status === 403 ? "Your account has no active clinical access. Contact your facility administrator."
      : "Clinical access could not be verified. Please retry.", response.status);
  const identity = await response.json();
  if ((identity.role !== "doctor" && identity.role !== "nurse") || !identity.facility_ids?.length) {
    throw new ClinicalSessionError("A clinical role and facility assignment are required.", 403);
  }
  if (!signal?.aborted) role = identity.role;
}

export async function revokeClinicalSession(): Promise<void> {
  const response = await fetch(`${apiUrl}/api/v1/auth/session/revoke`, {
    method: "POST", cache: "no-store", signal: AbortSignal.timeout(10_000),
    headers: { Authorization: `Bearer ${await clinicalAccessToken()}` },
  });
  // An already expired/revoked credential has no remaining platform access.
  if (!response.ok && response.status !== 401 && response.status !== 403) {
    throw new ClinicalSessionError("Session revocation failed. Please retry signing out.", response.status);
  }
  role = null;
  window.sessionStorage.removeItem("medikiosk.access_token");
  window.sessionStorage.removeItem("medikiosk.clinician_role");
}
