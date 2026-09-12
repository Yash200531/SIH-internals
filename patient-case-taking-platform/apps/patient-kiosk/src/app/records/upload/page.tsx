"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AccessibilityControls } from "../../../components/AccessibilityControls";
import { TouchButton } from "../../../components/TouchButton";
import {
  PatientDocument,
  PatientSession,
  getPatientDocument,
  listPatientDocuments,
  readPatientSession,
  uploadPatientPrescription,
} from "../../../lib/patientPortal";

const ACCEPTED_TYPES = ["application/pdf", "image/png", "image/jpeg", "image/webp"];
const TERMINAL_STATES = new Set(["reviewed", "scan_rejected", "processing_failed", "cancelled"]);

const STATE_LABELS: Record<string, string> = {
  initiated: "Preparing secure upload · सुरक्षित अपलोड तैयार हो रहा है",
  quarantined: "Uploaded safely · सुरक्षित रूप से अपलोड हुआ",
  scanning: "Safety scan · सुरक्षा जाँच",
  scan_passed: "Safety scan passed · सुरक्षा जाँच पूरी",
  processing: "Reading document · दस्तावेज़ पढ़ा जा रहा है",
  review_required: "Waiting for clinician review · डॉक्टर की जाँच बाकी",
  reviewed: "Clinician reviewed · डॉक्टर ने जाँच लिया",
  scan_rejected: "File could not pass the safety scan · फ़ाइल सुरक्षा जाँच में असफल",
  processing_failed: "Processing needs staff help · प्रक्रिया के लिए स्टाफ की मदद चाहिए",
  cancelled: "Upload cancelled · अपलोड रद्द",
};

export default function PrescriptionUploadPage() {
  const [session, setSession] = useState<PatientSession | null>(null);
  const [documents, setDocuments] = useState<PatientDocument[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [encounterId, setEncounterId] = useState("");
  const [consentId, setConsentId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    queueMicrotask(() => {
      const activeSession = readPatientSession();
      setSession(activeSession);
      setEncounterId(localStorage.getItem("notmid-encounter-id") || "");
      setConsentId(localStorage.getItem("notmid-consent-id") || "");
      if (activeSession) {
        void listPatientDocuments(activeSession).then(setDocuments).catch(() => {
          setError("Document status is unavailable · दस्तावेज़ की स्थिति उपलब्ध नहीं है");
        });
      }
    });
  }, []);

  useEffect(() => {
    if (!session || documents.every((item) => TERMINAL_STATES.has(item.state))) return;
    const timer = window.setInterval(() => {
      void Promise.all(documents.map((item) => getPatientDocument(session, item.id)))
        .then(setDocuments)
        .catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [documents, session]);

  function chooseFile(selected: File | null) {
    setError("");
    if (!selected) {
      setFile(null);
      return;
    }
    if (!ACCEPTED_TYPES.includes(selected.type)) {
      setError("Use PDF, PNG, JPG or WebP · PDF, PNG, JPG या WebP चुनें");
      setFile(null);
      return;
    }
    if (selected.size > 10 * 1024 * 1024) {
      setError("File must be 10 MB or smaller · फ़ाइल 10 MB या कम होनी चाहिए");
      setFile(null);
      return;
    }
    setFile(selected);
  }

  async function submit() {
    if (!session || !file || !encounterId || !consentId) return;
    setBusy(true);
    setError("");
    setStatus("Uploading to the secure review pipeline · सुरक्षित जाँच के लिए अपलोड हो रहा है");
    try {
      const document = await uploadPatientPrescription(
        session,
        file,
        encounterId,
        consentId,
      );
      setDocuments((current) => [document, ...current.filter((item) => item.id !== document.id)]);
      setFile(null);
      setStatus("Upload complete. Safety scan will begin next · अपलोड पूरा हुआ");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Upload failed");
      setStatus("");
    } finally {
      setBusy(false);
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

        <p className="mk-eyebrow">Prescription upload · पर्चा अपलोड</p>
        <h1 className="mk-display my-3 text-4xl sm:text-6xl">Share a clear copy for clinician review.</h1>
        <p className="max-w-2xl text-lg text-[var(--mk-ink-muted)]">Your file is safety-scanned, read locally with real PP-OCRv5, and checked by a clinician before any fact appears in your record.</p>

        {!session ? (
          <section className="mk-card mt-7 p-6" role="alert">
            <h2 className="text-xl font-bold">Secure patient access is required · सुरक्षित प्रवेश आवश्यक है</h2>
            <Link className="mk-button mk-button--success mt-4" href="/records">Open records first · पहले रिकॉर्ड खोलें</Link>
          </section>
        ) : (
          <>
            <section className="mk-card mt-7 p-6 sm:p-8">
              <span className="mk-pill mk-pill--success">PDF / PNG / JPG / WebP · max 10 MB</span>
              <label className="mt-6 block font-bold" htmlFor="prescription-file">Choose prescription · पर्चा चुनें</label>
              <input id="prescription-file" className="mt-2 block min-h-12 w-full rounded-xl border border-[var(--mk-border)] bg-white p-3" type="file" accept=".pdf,.png,.jpg,.jpeg,.webp" onChange={(event) => chooseFile(event.target.files?.[0] || null)} />
              {file && <p className="mt-3 rounded-xl bg-[var(--mk-success-soft)] p-3 font-bold">{file.name} · {(file.size / 1024).toFixed(1)} KB</p>}

              <details className="mt-5 rounded-xl bg-[var(--mk-surface-muted)] p-4">
                <summary className="cursor-pointer font-bold">Local synthetic IDs · स्थानीय सिंथेटिक आईडी</summary>
                <label className="mt-4 block text-sm font-bold" htmlFor="encounter-id">Encounter ID</label>
                <input id="encounter-id" className="mt-1 w-full rounded-lg border border-[var(--mk-border)] p-3" value={encounterId} onChange={(event) => setEncounterId(event.target.value)} />
                <label className="mt-3 block text-sm font-bold" htmlFor="consent-id">Consent ID</label>
                <input id="consent-id" className="mt-1 w-full rounded-lg border border-[var(--mk-border)] p-3" value={consentId} onChange={(event) => setConsentId(event.target.value)} />
              </details>

              <TouchButton className="mt-5" variant="success" size="large" disabled={busy || !file || !encounterId || !consentId} onClick={() => void submit()}>{busy ? "Uploading… · अपलोड…" : "Upload securely · सुरक्षित अपलोड"}</TouchButton>
              <p className="mt-3 text-xs text-[var(--mk-ink-muted)]">The original stays immutable in private object storage. Raw OCR is never shown as verified medical truth.</p>
            </section>

            <div className="mt-5" role="status" aria-live="polite">{status && <p className="rounded-xl bg-[var(--mk-success-soft)] p-4 font-bold">{status}</p>}</div>
            {error && <p className="mt-5 rounded-xl border-2 border-[var(--mk-danger)] bg-[var(--mk-danger-soft)] p-4 font-bold" role="alert">{error}</p>}

            <section className="mk-card mt-7 p-6" aria-labelledby="upload-status-title">
              <h2 id="upload-status-title" className="mk-display text-3xl">Your uploads · आपके अपलोड</h2>
              {documents.length === 0 ? <p className="mt-4 text-[var(--mk-ink-muted)]">No prescriptions uploaded yet · अभी कोई पर्चा अपलोड नहीं हुआ</p> : <ul className="mt-5 space-y-3">{documents.map((document) => <li key={document.id} className="rounded-xl border border-[var(--mk-border)] p-4"><div className="flex flex-wrap items-center justify-between gap-3"><p className="font-bold">Prescription · {new Date(document.created_at).toLocaleString("en-IN")}</p><span className={`mk-pill ${document.state === "reviewed" ? "mk-pill--success" : document.state.includes("failed") || document.state === "scan_rejected" ? "mk-pill--danger" : "mk-pill--warning"}`}>{document.state.replaceAll("_", " ")}</span></div><p className="mt-2 text-sm text-[var(--mk-ink-muted)]">{STATE_LABELS[document.state] || "Processing status updated · स्थिति अपडेट हुई"}</p></li>)}</ul>}
            </section>
          </>
        )}
      </div>
    </main>
  );
}
