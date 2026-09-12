"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AccessibilityControls } from "../../components/AccessibilityControls";
import { TouchButton } from "../../components/TouchButton";
import {
  PatientConsent,
  PatientSession,
  listPatientConsents,
  readPatientSession,
  revokePatientConsent,
} from "../../lib/patientPortal";

export default function ConsentsPage() {
  const [session, setSession] = useState<PatientSession | null>(null);
  const [consents, setConsents] = useState<PatientConsent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    queueMicrotask(() => {
      const activeSession = readPatientSession();
      setSession(activeSession);
      if (!activeSession) {
        setLoading(false);
        return;
      }
      void listPatientConsents(activeSession)
        .then(setConsents)
        .catch((caught) => setError(caught instanceof Error ? caught.message : "Consent service unavailable"))
        .finally(() => setLoading(false));
    });
  }, []);

  async function revoke(consentId: string) {
    if (!session) return;
    setError("");
    try {
      const revoked = await revokePatientConsent(session, consentId);
      setConsents((current) => current.map((item) => item.id === revoked.id ? revoked : item));
      if (localStorage.getItem("notmid-consent-id") === consentId) {
        localStorage.removeItem("notmid-consent-id");
        localStorage.setItem("notmid-retain-audio", "false");
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Consent could not be revoked");
    }
  }

  return (
    <main className="min-h-dvh bg-[var(--mk-canvas)] px-4 py-6 text-[var(--mk-ink)] sm:px-8">
      <AccessibilityControls />
      <div className="mx-auto max-w-4xl">
        <header className="mb-8 flex flex-wrap items-center justify-between gap-4">
          <Link className="mk-wordmark no-underline" href="/">Medi<em>Kiosk</em></Link>
          <Link className="mk-button mk-button--soft" href="/records">Records · रिकॉर्ड</Link>
        </header>
        <p className="mk-eyebrow">Consent control · सहमति नियंत्रण</p>
        <h1 className="mk-display my-3 text-4xl sm:text-6xl">Your permission stays in your hands.</h1>
        <p className="max-w-2xl text-lg text-[var(--mk-ink-muted)]">Review or withdraw your active local treatment consent. Withdrawal stops new use; retention and already signed records follow facility policy.</p>

        {loading && <p className="mk-card mt-7 p-6" role="status" aria-live="polite">Loading consent history · सहमति इतिहास लाया जा रहा है…</p>}
        {error && <p className="mt-7 rounded-xl border-2 border-[var(--mk-danger)] bg-[var(--mk-danger-soft)] p-4 font-bold" role="alert">{error}</p>}
        {!loading && !session && <section className="mk-card mt-7 p-6" role="alert"><p className="font-bold">Secure patient access is required · सुरक्षित रोगी प्रवेश आवश्यक है</p><Link className="mk-button mk-button--success mt-4" href="/records">Open records · रिकॉर्ड खोलें</Link></section>}
        {!loading && session && consents.length === 0 && <p className="mk-card mt-7 p-6">No saved consent yet · अभी कोई सहमति सुरक्षित नहीं है</p>}
        {!loading && session && consents.length > 0 && <ul className="mt-7 space-y-4">{consents.map((consent) => <li key={consent.id} className="mk-card p-6"><div className="flex flex-wrap items-start justify-between gap-4"><div><span className={`mk-pill ${consent.status === "granted" ? "mk-pill--success" : "mk-pill--warning"}`}>{consent.status}</span><h2 className="mt-3 text-xl font-bold">Treatment and document review · इलाज और दस्तावेज़ जाँच</h2><p className="mt-1 text-sm text-[var(--mk-ink-muted)]">Granted {new Date(consent.granted_at).toLocaleString("en-IN")}</p><p className="mt-1 text-xs text-[var(--mk-ink-muted)]">Encounter {consent.encounter_id}</p></div>{consent.status === "granted" && <TouchButton variant="danger" onClick={() => void revoke(consent.id)}>Withdraw · वापस लें</TouchButton>}</div></li>)}</ul>}
      </div>
    </main>
  );
}
