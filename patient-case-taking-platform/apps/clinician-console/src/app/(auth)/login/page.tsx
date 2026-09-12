"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("doctor@example.test");
  const [userId, setUserId] = useState("");
  const [tenantId, setTenantId] = useState("");
  const [facilityId, setFacilityId] = useState("");
  const [role, setRole] = useState<"doctor" | "nurse">("doctor");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleLogin(event: React.FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const query = new URLSearchParams({
        user_id: userId,
        email,
        role,
        tenant_id: tenantId,
      });
      query.append("facility_ids", facilityId);
      const response = await fetch(`${apiUrl}/api/v1/auth/token?${query}`, {
        method: "POST",
      });
      const payload = (await response.json().catch(() => null)) as {
        token?: string;
        detail?: string;
      } | null;
      if (!response.ok || !payload?.token) {
        throw new Error(payload?.detail ?? "Development sign-in is unavailable.");
      }
      window.sessionStorage.setItem("medikiosk.access_token", payload.token);
      window.sessionStorage.setItem("medikiosk.clinician_role", role);
      router.push("/doctor");
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Development sign-in failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="dev-login">
      <section className="mk-card dev-login-card" aria-labelledby="login-title">
        <span className="mk-eyebrow">Local engineering access</span>
        <h1 id="login-title" className="mk-display">MediKiosk clinician console</h1>
        <p>This local sign-in is for synthetic testing only. Use your organization’s configured sign-in for clinical access.</p>

        {error && <p className="dev-login-error" role="alert">{error}</p>}
        <form onSubmit={handleLogin}>
          <label htmlFor="login-role">Clinical role</label>
          <select id="login-role" value={role}
            onChange={(event) => setRole(event.target.value as "doctor" | "nurse")}>
            <option value="doctor">Doctor</option>
            <option value="nurse">Nurse</option>
          </select>

          <label htmlFor="login-email">Synthetic email</label>
          <input id="login-email" type="email" value={email}
            onChange={(event) => setEmail(event.target.value)} required />

          <label htmlFor="login-user">User UUID</label>
          <input id="login-user" value={userId} onChange={(event) => setUserId(event.target.value)}
            placeholder="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" required />

          <label htmlFor="login-tenant">Tenant UUID</label>
          <input id="login-tenant" value={tenantId} onChange={(event) => setTenantId(event.target.value)}
            placeholder="11111111-1111-4111-8111-111111111111" required />

          <label htmlFor="login-facility">Facility UUID</label>
          <input id="login-facility" value={facilityId}
            onChange={(event) => setFacilityId(event.target.value)}
            placeholder="22222222-2222-4222-8222-222222222222" required />

          <button className="mk-button mk-button--primary" type="submit" disabled={loading}>
            {loading ? "Starting local session…" : "Start local clinical session"}
          </button>
        </form>
      </section>
    </main>
  );
}
