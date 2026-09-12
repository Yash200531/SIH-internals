"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AccessibilityControls } from "../../components/AccessibilityControls";
import { TouchButton } from "../../components/TouchButton";
import { PatientLongitudinalPanel } from "../../components/records/PatientLongitudinalPanel";
import {
  PatientDashboard,
  PatientLongitudinalTimeline,
  PatientReportDetail,
  PatientReportListItem,
  PatientSession,
  clearPatientSession,
  createDemoPatientSession,
  downloadPatientReport,
  getPatientDashboard,
  getPatientLongitudinalTimeline,
  getPatientReport,
  listPatientReports,
  readPatientSession,
} from "../../lib/patientPortal";

const COPY = {
  hi: {
    eyebrow: "आपका स्वास्थ्य रिकॉर्ड",
    title: "रिपोर्ट, एक सुरक्षित जगह पर।",
    intro: "केवल डॉक्टर द्वारा हस्ताक्षरित रिपोर्ट और जाँचे गए दस्तावेज़ यहाँ दिखते हैं।",
    access: "सिंथेटिक डेमो रिकॉर्ड खोलें",
    accessHelp: "केवल स्थानीय विकास के लिए। असली रोगी जानकारी का उपयोग न करें।",
    reports: "हस्ताक्षरित रिपोर्ट",
    timeline: "जाँचे गए दस्तावेज़",
    empty: "अभी कोई हस्ताक्षरित रिपोर्ट नहीं है।",
    emptyHelp: "डॉक्टर के हस्ताक्षर के बाद रिपोर्ट यहाँ दिखाई देगी।",
    view: "पूरी रिपोर्ट देखें",
    download: "डाउनलोड करें",
    close: "बंद करें",
    retry: "फिर कोशिश करें",
    end: "सुरक्षित सत्र बंद करें",
    home: "होम",
    loading: "आपके रिकॉर्ड सुरक्षित रूप से लाए जा रहे हैं…",
    safety: "यह रिकॉर्ड आपातकालीन सलाह नहीं है। परेशानी बढ़े तो तुरंत स्टाफ को बुलाएँ।",
  },
  en: {
    eyebrow: "Your health record",
    title: "Reports, in one safe place.",
    intro: "Only doctor-signed reports and clinician-reviewed document facts appear here.",
    access: "Open synthetic demo records",
    accessHelp: "Local development only. Do not use real patient information.",
    reports: "Signed reports",
    timeline: "Reviewed documents",
    empty: "No signed reports yet.",
    emptyHelp: "A report will appear here after the doctor signs it.",
    view: "View full report",
    download: "Download",
    close: "Close",
    retry: "Try again",
    end: "End secure session",
    home: "Home",
    loading: "Loading your records securely…",
    safety: "This record is not emergency advice. Call staff now if symptoms worsen.",
  },
};

export default function RecordsPage() {
  const [language, setLanguage] = useState<"hi" | "en">("hi");
  const [session, setSession] = useState<PatientSession | null>(null);
  const [dashboard, setDashboard] = useState<PatientDashboard | null>(null);
  const [reports, setReports] = useState<PatientReportListItem[]>([]);
  const [longitudinal, setLongitudinal] = useState<PatientLongitudinalTimeline | null>(null);
  const [timelineUnavailable, setTimelineUnavailable] = useState(false);
  const [selected, setSelected] = useState<PatientReportDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const copy = COPY[language];

  const load = useCallback(async (activeSession: PatientSession) => {
    setLoading(true);
    setError("");
    try {
      const [nextDashboard, nextReports] = await Promise.all([
        getPatientDashboard(activeSession),
        listPatientReports(activeSession),
      ]);
      setDashboard(nextDashboard);
      setReports(nextReports);
      try {
        setLongitudinal(await getPatientLongitudinalTimeline(activeSession));
        setTimelineUnavailable(false);
      } catch {
        setLongitudinal(null);
        setTimelineUnavailable(true);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Patient records are unavailable");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => {
      const activeSession = readPatientSession();
      setSession(activeSession);
      if (activeSession) void load(activeSession);
      else setLoading(false);
    });
  }, [load]);

  async function openDemo() {
    setLoading(true);
    setError("");
    try {
      const activeSession = await createDemoPatientSession();
      setSession(activeSession);
      await load(activeSession);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Demo access is unavailable");
      setLoading(false);
    }
  }

  async function openReport(reportId: string) {
    if (!session) return;
    setLoading(true);
    setError("");
    try {
      setSelected(await getPatientReport(session, reportId));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Report is unavailable");
    } finally {
      setLoading(false);
    }
  }

  async function download(reportId: string) {
    if (!session) return;
    setError("");
    try {
      await downloadPatientReport(session, reportId);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Download is unavailable");
    }
  }

  function endSession() {
    clearPatientSession();
    setSession(null);
    setDashboard(null);
    setReports([]);
    setLongitudinal(null);
    setTimelineUnavailable(false);
    setSelected(null);
  }

  return (
    <main className="min-h-dvh bg-[var(--mk-canvas)] px-4 py-6 text-[var(--mk-ink)] sm:px-8">
      <AccessibilityControls />
      <div className="mx-auto max-w-6xl">
        <header className="mb-8 flex flex-wrap items-center justify-between gap-4">
          <Link className="mk-wordmark no-underline" href="/">Medi<em>Kiosk</em></Link>
          <div className="flex flex-wrap gap-2">
            <button className="language-chip" aria-pressed={language === "hi"} onClick={() => setLanguage("hi")}>हिंदी</button>
            <button className="language-chip" aria-pressed={language === "en"} onClick={() => setLanguage("en")}>English</button>
          </div>
        </header>

        <section className="mb-7 max-w-3xl">
          <p className="mk-eyebrow">{copy.eyebrow}</p>
          <h1 className="mk-display my-3 text-4xl sm:text-6xl">{copy.title}</h1>
          <p className="text-lg text-[var(--mk-ink-muted)]">{copy.intro}</p>
        </section>

        {loading && (
          <div className="mk-card p-6" role="status" aria-live="polite" aria-busy="true">
            <span className="mk-pill">● {copy.loading}</span>
          </div>
        )}

        {error && (
          <div className="mb-6 rounded-2xl border-2 border-[var(--mk-danger)] bg-[var(--mk-danger-soft)] p-5" role="alert">
            <p className="font-bold">{error}</p>
            {session && <TouchButton className="mt-3" variant="secondary" onClick={() => void load(session)}>{copy.retry}</TouchButton>}
          </div>
        )}

        {!loading && !session && (
          <section className="mk-card max-w-2xl p-7">
            <span className="mk-pill mk-pill--warning">Local demo · synthetic data only</span>
            <h2 className="mk-display my-4 text-3xl">{copy.access}</h2>
            <p className="mb-5 text-[var(--mk-ink-muted)]">{copy.accessHelp}</p>
            <TouchButton variant="success" size="large" onClick={() => void openDemo()}>{copy.access}</TouchButton>
          </section>
        )}

        {!loading && session && dashboard && (
          <>
            <div className="mb-6 grid gap-4 sm:grid-cols-2">
              <div className="mk-card p-6"><p className="mk-eyebrow">{copy.reports}</p><p className="mk-display mt-2 text-5xl">{dashboard.signed_report_count}</p></div>
              <div className="mk-card p-6"><p className="mk-eyebrow">{copy.timeline}</p><p className="mk-display mt-2 text-5xl">{dashboard.reviewed_timeline_count}</p></div>
            </div>

            <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
              <section className="mk-card p-6" aria-labelledby="reports-heading">
                <h2 id="reports-heading" className="mk-display text-3xl">{copy.reports}</h2>
                {reports.length === 0 ? (
                  <div className="mt-5 rounded-2xl bg-[var(--mk-surface-muted)] p-5">
                    <p className="font-bold">{copy.empty}</p><p className="mt-1 text-sm text-[var(--mk-ink-muted)]">{copy.emptyHelp}</p>
                  </div>
                ) : (
                  <ul className="mt-5 space-y-4">
                    {reports.map((report) => (
                      <li key={report.id} className="rounded-2xl border border-[var(--mk-border)] p-5">
                        <span className="mk-pill mk-pill--success">Doctor signed</span>
                        <h3 className="mt-3 text-xl font-bold">{report.title}</h3>
                        <p className="mt-1 text-sm text-[var(--mk-ink-muted)]">{new Date(report.signed_at).toLocaleString(language === "hi" ? "hi-IN" : "en-IN")}</p>
                        <div className="mt-4 flex flex-wrap gap-3">
                          <TouchButton variant="primary" onClick={() => void openReport(report.id)}>{copy.view}</TouchButton>
                          <TouchButton variant="secondary" onClick={() => void download(report.id)}>{copy.download}</TouchButton>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <PatientLongitudinalPanel language={language} timeline={longitudinal}
                fallback={dashboard.recent_timeline} unavailable={timelineUnavailable} />
            </div>

            <div className="mt-6 flex flex-wrap gap-3">
              <Link className="mk-button mk-button--success" href="/records/upload">Upload prescription · पर्चा अपलोड करें</Link>
              <TouchButton variant="secondary" onClick={endSession}>{copy.end}</TouchButton>
              <Link className="mk-button mk-button--soft" href="/">{copy.home}</Link>
            </div>
          </>
        )}

        {selected && (
          <div className="fixed inset-0 z-50 overflow-y-auto bg-black/60 p-4" role="dialog" aria-modal="true" aria-labelledby="report-title">
            <article className="mx-auto my-6 max-w-3xl rounded-3xl bg-white p-6 shadow-2xl sm:p-9">
              <div className="flex items-start justify-between gap-4"><div><span className="mk-pill mk-pill--success">Signed · हस्ताक्षरित</span><h2 id="report-title" className="mk-display mt-3 text-3xl">{selected.content.chief_complaint}</h2></div><TouchButton variant="secondary" onClick={() => setSelected(null)}>{copy.close}</TouchButton></div>
              <ReportSection title="History · इतिहास" values={selected.content.history_of_present_illness} />
              <ReportSection title="Relevant negatives · अनुपस्थित लक्षण" values={selected.content.relevant_negatives} />
              <ReportSection title="Reviewed document facts · जाँचे गए दस्तावेज़" values={selected.content.document_facts} />
              <ReportSection title="Safety flags · सुरक्षा संकेत" values={selected.content.red_flags} danger />
              <ReportSection title="Uncertainties · जिन बातों की पुष्टि बाकी है" values={selected.content.uncertainties} />
              <p className="mt-6 rounded-xl bg-[var(--mk-warning-soft)] p-4 text-sm font-bold">{copy.safety}</p>
              <p className="mt-4 break-all text-xs text-[var(--mk-ink-muted)]">Integrity SHA-256: {selected.signature_sha256}</p>
              <TouchButton className="mt-5" variant="primary" onClick={() => void download(selected.id)}>{copy.download}</TouchButton>
            </article>
          </div>
        )}
      </div>
    </main>
  );
}

function ReportSection({ title, values, danger = false }: { title: string; values: string[]; danger?: boolean }) {
  return (
    <section className={`mt-6 rounded-2xl p-5 ${danger ? "bg-[var(--mk-danger-soft)]" : "bg-[var(--mk-surface-muted)]"}`}>
      <h3 className="font-bold">{title}</h3>
      {values.length === 0 ? <p className="mt-2 text-sm text-[var(--mk-ink-muted)]">None recorded · दर्ज नहीं</p> : <ul className="mt-2 list-disc space-y-1 pl-5">{values.map((value) => <li key={value}>{value}</li>)}</ul>}
    </section>
  );
}
