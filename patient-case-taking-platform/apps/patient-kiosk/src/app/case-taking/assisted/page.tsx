"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { AccessibilityControls } from "@/components/AccessibilityControls";
import { AudioPrompt } from "@/components/AudioPrompt";
import { TouchButton } from "@/components/TouchButton";
import { VoiceInput } from "@/components/VoiceInput";
import {
  ClinicalSummaryResponse,
  DialogueResponse,
  generateClinicalSummary,
  getNextQuestion,
} from "@/lib/clinicalAi";
import { confirmPatientSafety, readPatientSession, submitPatientIntake } from "@/lib/patientPortal";
import { prefetchPrompt } from "@/lib/tts";

type Phase = "complaint" | "question" | "emergency" | "summary";
type ReviewDecision = "editing" | "accepted" | "rejected";

const COPY = {
  en: {
    eyebrow: "Assisted questions · Offline mock",
    title: "Tell us what is happening.",
    intro: "Answer one question at a time by voice or touch. You can correct every answer.",
    complaint: "What brings you here today?",
    complaintHelp: "For example: I have had stomach pain since yesterday.",
    continue: "Continue",
    thinking: "Choosing the next safe question…",
    unavailable: "Assisted questions are unavailable. Some confirmed answers may already be saved. Please ask nearby staff for help.",
    safetyUnavailable: "The safety check could not be completed. Please call a nearby nurse or doctor before continuing.",
    safetySaved: "A warning was saved for clinician review. Staff have not yet acknowledged it. Please call a nearby nurse or doctor now.",
    manual: "Use the touch questionnaire",
    answer: "Type your answer",
    submitAnswer: "Confirm answer",
    emergencyTitle: "Please call a staff member now",
    emergencyBody: "A warning symptom was detected by a fixed safety rule. Stop the routine questions and alert a nurse or doctor immediately.",
    calledStaff: "I have called staff",
    summaryTitle: "Check what we understood",
    summaryHelp: "This is an editable draft from your confirmed answers. It is not a diagnosis or signed record.",
    history: "Your answers",
    warnings: "Warning symptoms",
    uncertainties: "Still missing or uncertain",
    accept: "Confirm for clinician review",
    reject: "Reject this draft",
    accepted: "Draft confirmed for clinician review. A clinician must still review and sign it.",
    rejected: "Draft rejected. Nothing was signed. You can return to the touch questionnaire.",
  },
  hi: {
    eyebrow: "सहायक प्रश्न · ऑफ़लाइन मॉक",
    title: "बताइए क्या परेशानी है।",
    intro: "आवाज़ या टच से एक-एक प्रश्न का उत्तर दें। हर उत्तर को आप सुधार सकते हैं।",
    complaint: "आज आपको क्या परेशानी है?",
    complaintHelp: "जैसे: कल से मेरे पेट में दर्द है।",
    continue: "आगे बढ़ें",
    thinking: "अगला सुरक्षित प्रश्न चुना जा रहा है…",
    unavailable: "सहायक प्रश्न अभी उपलब्ध नहीं हैं। कुछ पुष्ट उत्तर सहेजे जा चुके हो सकते हैं। पास के स्टाफ से मदद माँगें।",
    safetyUnavailable: "सुरक्षा जाँच पूरी नहीं हो सकी। आगे बढ़ने से पहले पास की नर्स या डॉक्टर को बुलाएँ।",
    safetySaved: "चेतावनी डॉक्टर की समीक्षा के लिए सहेजी गई है। स्टाफ ने अभी इसकी पुष्टि नहीं की है। पास की नर्स या डॉक्टर को अभी बुलाएँ।",
    manual: "टच प्रश्नावली का उपयोग करें",
    answer: "अपना उत्तर लिखें",
    submitAnswer: "उत्तर की पुष्टि करें",
    emergencyTitle: "अभी स्टाफ को बुलाइए",
    emergencyBody: "एक तय सुरक्षा नियम ने खतरे का लक्षण पहचाना है। सामान्य प्रश्न रोकें और तुरंत नर्स या डॉक्टर को बताइए।",
    calledStaff: "मैंने स्टाफ को बुलाया है",
    summaryTitle: "जाँचें कि हमने क्या समझा",
    summaryHelp: "यह आपके पक्के किए उत्तरों से बना सुधार योग्य मसौदा है। यह निदान या हस्ताक्षरित रिकॉर्ड नहीं है।",
    history: "आपके उत्तर",
    warnings: "खतरे के लक्षण",
    uncertainties: "अभी अधूरा या अनिश्चित",
    accept: "डॉक्टर की समीक्षा के लिए पुष्टि करें",
    reject: "यह मसौदा अस्वीकार करें",
    accepted: "मसौदा डॉक्टर की समीक्षा के लिए पक्का हुआ। डॉक्टर की जाँच और हस्ताक्षर अभी भी जरूरी हैं।",
    rejected: "मसौदा अस्वीकार हुआ। कुछ भी हस्ताक्षरित नहीं हुआ। आप टच प्रश्नावली पर लौट सकते हैं।",
  },
};

export default function AssistedQuestionPage() {
  const [language, setLanguage] = useState<"hi" | "en">("hi");
  const [phase, setPhase] = useState<Phase>("complaint");
  const [chiefComplaint, setChiefComplaint] = useState("");
  const [answerDraft, setAnswerDraft] = useState("");
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [question, setQuestion] = useState<DialogueResponse | null>(null);
  const [summary, setSummary] = useState<ClinicalSummaryResponse | null>(null);
  const [historyDraft, setHistoryDraft] = useState("");
  const [uncertaintyDraft, setUncertaintyDraft] = useState("");
  const [decision, setDecision] = useState<ReviewDecision>("editing");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [safetySaved, setSafetySaved] = useState(false);
  const emergencyRef = useRef<HTMLElement>(null);
  const [context, setContext] = useState(() => ({
    tenantId: crypto.randomUUID(),
    sessionId: crypto.randomUUID(),
    encounterId: crypto.randomUUID(),
    consentId: crypto.randomUUID(),
    retainAudio: false,
    audioRetentionConsent: false,
  }));
  const copy = COPY[language];

  useEffect(() => {
    if (phase === "emergency") emergencyRef.current?.focus();
  }, [phase]);

  useEffect(() => {
    queueMicrotask(() => {
      const patient = readPatientSession();
      const storedLanguage = localStorage.getItem("notmid-language");
      if (storedLanguage === "hi" || storedLanguage === "en") setLanguage(storedLanguage);
      setContext((current) => ({
        ...current,
        tenantId: patient?.tenantId || current.tenantId,
        sessionId: localStorage.getItem("notmid-kiosk-session-id") || current.sessionId,
        encounterId: localStorage.getItem("notmid-encounter-id") || current.encounterId,
        consentId: localStorage.getItem("notmid-consent-id") || current.consentId,
        retainAudio: localStorage.getItem("notmid-retain-audio") === "true",
        audioRetentionConsent: localStorage.getItem("notmid-retain-audio") === "true",
      }));
    });
  }, []);

  async function loadNextQuestion(
    complaint: string,
    collectedAnswers: Record<string, string>,
    lastPatientMessage: string,
  ) {
    setBusy(true);
    setError("");
    setStatus(copy.thinking);
    try {
      try {
        const patient = readPatientSession();
        if (!patient) throw new Error("Patient access required");
        const safety = await confirmPatientSafety(patient, {
          encounter_id: context.encounterId,
          consent_id: context.consentId,
          input_version: Object.keys(collectedAnswers).length + 1,
          chief_complaint: complaint,
          confirmed_answers: collectedAnswers,
        });
        if (safety.interrupt_required) {
          prefetchPrompt(`${copy.emergencyTitle}. ${copy.emergencyBody}`, language);
          setSafetySaved(true);
          setPhase("emergency");
          setStatus(copy.safetySaved);
          return;
        }
      } catch {
        setError(copy.safetyUnavailable);
        setStatus(copy.safetyUnavailable);
        return;
      }
      const response = await getNextQuestion({
        tenantId: context.tenantId,
        sessionId: context.sessionId,
        language,
        chiefComplaint: complaint,
        lastPatientMessage,
        collectedAnswers,
      });
      setQuestion(response);

      if (response.escalation_required) {
        prefetchPrompt(`${copy.emergencyTitle}. ${copy.emergencyBody}`, language);
        setPhase("emergency");
        setStatus(copy.emergencyTitle);
      } else if (response.answer_type === "review") {
        setStatus(language === "hi" ? "मसौदा बनाया जा रहा है…" : "Preparing the draft…");
        const generated = await generateClinicalSummary({
          tenantId: context.tenantId,
          encounterId: context.encounterId,
          language,
          chiefComplaint: complaint,
          confirmedAnswers: collectedAnswers,
        });
        setSummary(generated);
        setHistoryDraft(generated.history_of_present_illness.join("\n"));
        setUncertaintyDraft(generated.uncertainties.join("\n"));
        setPhase("summary");
        setStatus(copy.summaryTitle);
      } else {
        prefetchPrompt(response.question, language);
        setPhase("question");
        setStatus(response.question);
      }
    } catch {
      setError(copy.unavailable);
      setStatus(copy.unavailable);
    } finally {
      setBusy(false);
    }
  }

  function submitComplaint(value: string) {
    const complaint = value.trim();
    if (!complaint) return;
    setChiefComplaint(complaint);
    void loadNextQuestion(complaint, {}, complaint);
  }

  function submitAnswer(value: string) {
    const answer = value.trim();
    if (!answer || !question) return;
    const nextAnswers = { ...answers, [question.next_domain]: answer };
    setAnswers(nextAnswers);
    setAnswerDraft("");
    void loadNextQuestion(chiefComplaint, nextAnswers, answer);
  }

  async function finalizeDecision(nextDecision: "accepted" | "rejected") {
    if (!summary) return;
    const patient = readPatientSession();
    if (!patient) {
      setError(copy.unavailable);
      return;
    }
    const history = historyDraft.split("\n").map((item) => item.trim()).filter(Boolean);
    const uncertainties = uncertaintyDraft.split("\n").map((item) => item.trim()).filter(Boolean);
    setBusy(true);
    setError("");
    setStatus(language === "hi" ? "पुष्टि सुरक्षित रूप से सहेजी जा रही है…" : "Saving your confirmation securely…");
    try {
      await submitPatientIntake(patient, {
        encounterId: context.encounterId,
        sessionId: context.sessionId,
        consentId: context.consentId,
        language,
        chiefComplaint,
        confirmedAnswers: answers,
        summaryDraft: {
          chief_complaint: summary.chief_complaint,
          history_of_present_illness: history.length > 0 ? history : summary.history_of_present_illness,
          relevant_negatives: summary.relevant_negatives,
          document_facts: summary.document_facts,
          red_flags: summary.red_flags,
          uncertainties,
        },
        decision: nextDecision,
        provider: summary.provider === "template-fallback" ? "template-fallback" : "mock",
      });
      setDecision(nextDecision);
      setStatus(nextDecision === "accepted" ? copy.accepted : copy.rejected);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : copy.unavailable);
      setStatus(copy.unavailable);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-dvh bg-[var(--mk-canvas)] px-4 py-8 text-[var(--mk-ink)] sm:px-8">
      <AccessibilityControls />
      <div className="mx-auto max-w-4xl">
        <header className="mb-8 flex flex-wrap items-center justify-between gap-4">
          <Link className="mk-wordmark no-underline" href="/">Medi<em>Kiosk</em></Link>
          <div className="flex gap-2" aria-label="Choose language">
            <button className="language-chip" aria-pressed={language === "hi"} onClick={() => setLanguage("hi")}>हिंदी</button>
            <button className="language-chip" aria-pressed={language === "en"} onClick={() => setLanguage("en")}>English</button>
          </div>
        </header>

        <div className="mb-4 rounded-2xl border border-[var(--mk-border)] bg-white px-4 py-3" role="status" aria-live="polite" aria-atomic="true">
          <div className="flex items-center gap-3"><span className="mk-pill mk-pill--success">● {busy ? "Working" : "Assistant ready"}</span><p className="m-0 text-sm text-[var(--mk-ink-muted)]">{status || copy.intro}</p></div>
        </div>

        {error && (
          <div className="mb-4 rounded-2xl border-2 border-[var(--mk-danger)] bg-[var(--mk-danger-soft)] p-5" role="alert">
            <p className="font-bold">{error}</p><Link className="mk-button mk-button--soft mt-3" href="/case-taking">{copy.manual}</Link>
          </div>
        )}

        {phase === "complaint" && (
          <section className="mk-card p-6 sm:p-10">
            <p className="mk-eyebrow">{copy.eyebrow}</p><h1 className="mk-display my-3 text-4xl sm:text-6xl">{copy.title}</h1><p className="max-w-2xl text-lg text-[var(--mk-ink-muted)]">{copy.intro}</p>
            <div className="mt-8 rounded-2xl bg-[var(--mk-surface-muted)] p-5"><h2 className="mb-2 font-[var(--mk-font-display)] text-2xl">{copy.complaint}</h2><p className="text-sm text-[var(--mk-ink-muted)]">{copy.complaintHelp}</p><AudioPrompt text={copy.complaint} language={language}/><VoiceInput language={language} context={context} disabled={busy} onTranscription={(text) => submitComplaint(text)}/><textarea className="mt-4 min-h-28 w-full rounded-xl border border-[var(--mk-border)] bg-white p-4 text-lg" value={chiefComplaint} onChange={(event) => setChiefComplaint(event.target.value)} aria-label={copy.complaint}/><TouchButton className="mt-3" variant="success" size="large" disabled={busy || !chiefComplaint.trim()} onClick={() => submitComplaint(chiefComplaint)}>{copy.continue}</TouchButton></div>
          </section>
        )}

        {phase === "question" && question && (
          <section className="mk-card p-6 sm:p-10">
            <div className="mb-5 flex flex-wrap items-center justify-between gap-3"><span className="mk-pill">SOCRATES · {question.next_domain.replaceAll("_", " ")}</span><span className="text-xs text-[var(--mk-ink-muted)]">Provider: {question.provider} · no external network</span></div>
            <AudioPrompt text={question.question} language={language} autoPlay/><h1 className="mk-display my-5 text-3xl sm:text-5xl">{question.question}</h1>
            <VoiceInput key={question.next_domain} language={language} context={context} disabled={busy} onTranscription={(text) => submitAnswer(text)}/>
            <div className="my-5 flex items-center gap-3 text-sm text-[var(--mk-ink-muted)]"><span className="h-px flex-1 bg-[var(--mk-border)]"/>or / या<span className="h-px flex-1 bg-[var(--mk-border)]"/></div>
            <label className="block font-bold" htmlFor="assisted-answer">{copy.answer}</label><textarea id="assisted-answer" className="mt-2 min-h-28 w-full rounded-xl border border-[var(--mk-border)] bg-white p-4 text-lg" value={answerDraft} onChange={(event) => setAnswerDraft(event.target.value)}/><TouchButton className="mt-3" variant="success" size="large" disabled={busy || !answerDraft.trim()} onClick={() => submitAnswer(answerDraft)}>{copy.submitAnswer}</TouchButton>
          </section>
        )}

        {phase === "emergency" && (
          <section ref={emergencyRef} tabIndex={-1} className="rounded-3xl border-4 border-[var(--mk-danger)] bg-[var(--mk-danger-soft)] p-6 sm:p-10" role="alert" aria-live="assertive">
            <span className="mk-pill mk-pill--danger">Urgent safety message · तुरंत सहायता</span><h1 className="mk-display my-4 text-4xl text-[var(--mk-danger)] sm:text-6xl">{copy.emergencyTitle}</h1><AudioPrompt text={`${copy.emergencyTitle}. ${copy.emergencyBody}`} language={language} autoPlay/><p className="mt-5 max-w-2xl text-lg font-bold">{copy.emergencyBody}</p><p className="my-5 rounded-xl bg-white p-4">{safetySaved ? copy.safetySaved : question?.question}</p><p className="mb-5 text-sm">Routine questions are paused · सामान्य प्रश्न रोक दिए गए हैं</p><TouchButton variant="danger" size="large" onClick={() => setStatus(copy.calledStaff)}>{copy.calledStaff}</TouchButton>
          </section>
        )}

        {phase === "summary" && summary && (
          <section className="mk-card p-6 sm:p-10">
            <span className="mk-pill mk-pill--warning">Mock-generated draft · clinician review required</span><h1 className="mk-display my-4 text-4xl sm:text-5xl">{copy.summaryTitle}</h1><p className="text-[var(--mk-ink-muted)]">{copy.summaryHelp}</p>
            {decision === "editing" ? <div className="mt-7 space-y-5"><label className="block font-bold" htmlFor="summary-history">{copy.history}</label><textarea id="summary-history" className="min-h-44 w-full rounded-xl border border-[var(--mk-border)] bg-[var(--mk-paper-50)] p-4" value={historyDraft} onChange={(event) => setHistoryDraft(event.target.value)}/><label className="block font-bold" htmlFor="summary-uncertainty">{copy.uncertainties}</label><textarea id="summary-uncertainty" className="min-h-24 w-full rounded-xl border border-[var(--mk-border)] bg-[var(--mk-paper-50)] p-4" value={uncertaintyDraft} onChange={(event) => setUncertaintyDraft(event.target.value)}/>{summary.red_flags.length > 0 && <div className="rounded-xl bg-[var(--mk-danger-soft)] p-4"><strong>{copy.warnings}</strong><p>{summary.red_flags.join(", ")}</p></div>}<div className="flex flex-wrap gap-3"><TouchButton variant="danger" size="large" disabled={busy} onClick={() => void finalizeDecision("rejected")}>{copy.reject}</TouchButton><TouchButton variant="success" size="large" disabled={busy} onClick={() => void finalizeDecision("accepted")}>{copy.accept}</TouchButton></div></div> : <div className={`mt-6 rounded-2xl p-5 ${decision === "accepted" ? "bg-[var(--mk-success-soft)]" : "bg-[var(--mk-danger-soft)]"}`} role="status"><p className="font-bold">{decision === "accepted" ? copy.accepted : copy.rejected}</p><div className="mt-3 flex flex-wrap gap-3"><Link className="mk-button mk-button--success" href="/records">Records · रिकॉर्ड</Link>{decision === "rejected" && <Link className="mk-button mk-button--soft" href="/case-taking">{copy.manual}</Link>}</div></div>}
          </section>
        )}
      </div>
    </main>
  );
}
