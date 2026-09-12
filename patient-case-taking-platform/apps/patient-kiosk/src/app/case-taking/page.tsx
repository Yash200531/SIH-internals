"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { TouchButton } from "@/components/TouchButton";
import { IconCard } from "@/components/IconCard";
import { AudioPrompt } from "@/components/AudioPrompt";
import { VoiceInput } from "@/components/VoiceInput";
import { ProgressBar } from "@/components/ProgressBar";
import { AccessibilityControls } from "@/components/AccessibilityControls";
import {
  getQuestionnaire,
  describeAnswers,
  Question,
} from "@/lib/questionnaires";
import { confirmPatientSafety, readPatientSession, submitPatientIntake } from "@/lib/patientPortal";

type Step =
  | { type: "choose_type" }
  | { type: "section_intro"; sectionIndex: number }
  | { type: "question"; sectionIndex: number; questionIndex: number }
  | { type: "review" }
  | { type: "submitting" }
  | { type: "emergency" }
  | { type: "done" };

export default function CaseTakingPage() {
  const router = useRouter();
  const [lang, setLang] = useState<"hi" | "en">("hi");
  const [voiceContext, setVoiceContext] = useState(() => ({
    tenantId: crypto.randomUUID(),
    sessionId: crypto.randomUUID(),
    encounterId: crypto.randomUUID(),
    consentId: crypto.randomUUID(),
    retainAudio: false,
    audioRetentionConsent: false,
  }));
  const [step, setStep] = useState<Step>({ type: "choose_type" });
  const [answers, setAnswers] = useState<Record<string, string | string[]>>({});
  const [selectedType, setSelectedType] = useState<"allopathic" | "ayush" | null>(null);
  const [submitError, setSubmitError] = useState("");
  const [checkingSafety, setCheckingSafety] = useState(false);
  const safetyInFlight = useRef(false);
  const emergencyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (step.type === "emergency") emergencyRef.current?.focus();
  }, [step.type]);

  useEffect(() => {
    queueMicrotask(() => {
      const selectedLanguage = localStorage.getItem("notmid-language");
      if (selectedLanguage === "en" || selectedLanguage === "hi") setLang(selectedLanguage);
      const storedConsentId = localStorage.getItem("notmid-consent-id");
      const retainAudio = localStorage.getItem("notmid-retain-audio") === "true";
      const patient = readPatientSession();
      setVoiceContext((current) => ({
        ...current,
        tenantId: patient?.tenantId || current.tenantId,
        sessionId: localStorage.getItem("notmid-kiosk-session-id") || current.sessionId,
        encounterId: localStorage.getItem("notmid-encounter-id") || current.encounterId,
        consentId: storedConsentId || current.consentId,
        retainAudio,
        audioRetentionConsent: retainAudio,
      }));
    });
  }, []);

  const questionnaire = selectedType ? getQuestionnaire(selectedType) : null;
  const sections = questionnaire?.sections || [];
  const totalSteps = sections.reduce((acc, s) => acc + s.questions.length, 0) + sections.length;

  const currentSection = step.type === "section_intro" || step.type === "question"
    ? sections[step.sectionIndex]
    : null;

  const currentQuestion: Question | null =
    step.type === "question" && currentSection
      ? currentSection.questions[step.questionIndex]
      : null;

  const questionsDone = sections
    .slice(0, step.type === "question" ? step.sectionIndex : step.type === "section_intro" ? step.sectionIndex : sections.length)
    .reduce((acc, s) => acc + s.questions.length, 0)
    + (step.type === "question" ? step.questionIndex : 0);

  async function handleAnswer(questionId: string, answer: string | string[]) {
      if (safetyInFlight.current) return;
      safetyInFlight.current = true;
      setCheckingSafety(true);
      setSubmitError("");
      const nextAnswers = { ...answers, [questionId]: answer };
      setAnswers(nextAnswers);
      try {
        const patient = readPatientSession();
        if (!patient) throw new Error("Patient access required");
        const confirmedAnswers = describeAnswers(questionnaire, nextAnswers, lang);
        const safety = await confirmPatientSafety(patient, {
          encounter_id: voiceContext.encounterId,
          consent_id: voiceContext.consentId,
          input_version: Object.keys(nextAnswers).length,
          chief_complaint: "",
          confirmed_answers: confirmedAnswers,
        });
        if (safety.interrupt_required) {
          setStep({ type: "emergency" });
          return;
        }

      // Advance to next question
      if (step.type === "question" && currentSection) {
        if (step.questionIndex < currentSection.questions.length - 1) {
          setStep({ type: "question", sectionIndex: step.sectionIndex, questionIndex: step.questionIndex + 1 });
        } else if (step.sectionIndex < sections.length - 1) {
          setStep({ type: "section_intro", sectionIndex: step.sectionIndex + 1 });
        } else {
          setStep({ type: "review" });
        }
      }
      } catch {
        setSubmitError(lang === "hi"
          ? "सुरक्षा जाँच पूरी नहीं हो सकी। आगे बढ़ने से पहले पास की नर्स या डॉक्टर को बुलाएँ।"
          : "The safety check could not be completed. Please call a nearby nurse or doctor before continuing.");
      } finally {
        safetyInFlight.current = false;
        setCheckingSafety(false);
      }
  }

  async function submitCase() {
    const patient = readPatientSession();
    if (!patient) {
      setSubmitError(lang === "hi" ? "सुरक्षित रोगी सत्र नहीं मिला।" : "Secure patient session not found.");
      return;
    }
    const confirmedAnswers = describeAnswers(questionnaire, answers, lang);
    const history = Object.entries(confirmedAnswers).map(([key, value]) => `${key.replaceAll("_", " ")}: ${value}`);
    if (history.length === 0) {
      setSubmitError(lang === "hi" ? "जमा करने से पहले कम से कम एक उत्तर दें।" : "Answer at least one question before submitting.");
      return;
    }
    setSubmitError("");
    setStep({ type: "submitting" });
    try {
      await submitPatientIntake(patient, {
        encounterId: voiceContext.encounterId,
        sessionId: voiceContext.sessionId,
        consentId: voiceContext.consentId,
        language: lang,
        chiefComplaint: selectedType === "ayush" ? "Structured AYUSH intake" : "Structured allopathic intake",
        confirmedAnswers,
        summaryDraft: {
          chief_complaint: selectedType === "ayush" ? "Structured AYUSH intake" : "Structured allopathic intake",
          history_of_present_illness: history,
          relevant_negatives: [],
          document_facts: [],
          red_flags: [],
          uncertainties: [],
        },
        decision: "accepted",
        provider: "template-fallback",
      });
      setStep({ type: "done" });
    } catch (caught) {
      setSubmitError(caught instanceof Error ? caught.message : "Intake could not be saved");
      setStep({ type: "review" });
    }
  }

  if (step.type === "emergency") {
    return (
      <main className="flex min-h-dvh flex-col items-center justify-center gap-6 px-6">
        <AccessibilityControls />
        <div ref={emergencyRef} tabIndex={-1} role="alert" className="max-w-2xl rounded-3xl border-4 border-red-600 bg-red-50 p-8">
          <h1 className="text-3xl font-bold text-red-800">{lang === "hi" ? "अभी स्टाफ को बुलाइए" : "Please call a staff member now"}</h1>
          <p className="mt-5 text-xl">{lang === "hi" ? "चेतावनी समीक्षा के लिए सहेजी गई है। स्टाफ ने अभी इसकी पुष्टि नहीं की है। सामान्य प्रश्न रोक दिए गए हैं। पास की नर्स या डॉक्टर को अभी बुलाएँ।" : "A warning was saved for clinician review. Staff have not yet acknowledged it. Routine questions are paused. Please call a nearby nurse or doctor now."}</p>
        </div>
      </main>
    );
  }

  // --- Choose type ---
  if (step.type === "choose_type") {
    return (
      <main className="flex min-h-dvh flex-col items-center justify-center gap-8 px-6">
        <AccessibilityControls />
        <h1 className="text-3xl font-bold text-primary text-center">
          {lang === "hi" ? "अपना इतिहास दर्ज करें" : "Record Your History"}
        </h1>
        <AudioPrompt
          text={lang === "hi" ? "कृपया अपना इलाज का प्रकार चुनें" : "Please select your treatment type"}
          language={lang}
        />
        <div className="flex flex-wrap gap-6 justify-center">
          <IconCard icon="✦" label={lang === "hi" ? "सहायक प्रश्न" : "Assisted Questions"} onSelect={() => router.push("/case-taking/assisted")} size="large" />
          <IconCard icon="🏥" label={lang === "hi" ? "एलोपैथिक" : "Allopathic"} onSelect={() => { setSelectedType("allopathic"); setStep({ type: "section_intro", sectionIndex: 0 }); }} size="large" />
          <IconCard icon="🧘" label={lang === "hi" ? "आयुष" : "AYUSH"} onSelect={() => { setSelectedType("ayush"); setStep({ type: "section_intro", sectionIndex: 0 }); }} size="large" />
        </div>
      </main>
    );
  }

  // --- Section intro ---
  if (step.type === "section_intro" && currentSection) {
    return (
      <main className="flex min-h-dvh flex-col items-center justify-center gap-8 px-6">
        <AccessibilityControls />
        <ProgressBar currentStep={questionsDone} totalSteps={totalSteps} />
        <div className="text-center space-y-4">
          <span className="text-6xl" aria-hidden="true">{currentSection.icon}</span>
          <h2 className="text-3xl font-bold text-primary">{currentSection.title[lang]}</h2>
        </div>
        <AudioPrompt text={currentSection.title[lang]} language={lang} />
        <TouchButton variant="success" size="large" onClick={() => setStep({ type: "question", sectionIndex: step.sectionIndex, questionIndex: 0 })}>
          {lang === "hi" ? "शुरू करें" : "Begin"}
        </TouchButton>
      </main>
    );
  }

  // --- Question ---
  if (step.type === "question" && currentQuestion) {
    return (
      <main className="flex min-h-dvh flex-col items-center justify-center gap-6 px-6">
        <AccessibilityControls />
        <ProgressBar currentStep={questionsDone} totalSteps={totalSteps} />
        <AudioPrompt text={currentQuestion.audio[lang]} language={lang} />
        <h2 className="text-2xl font-bold text-primary text-center max-w-2xl">{currentQuestion.label[lang]}</h2>
        {submitError && <p role="alert" className="max-w-2xl rounded-xl bg-red-50 p-4 font-bold text-red-700">{submitError}</p>}
        {checkingSafety && <p role="status">{lang === "hi" ? "सुरक्षा जाँच जारी है…" : "Checking confirmed answer…"}</p>}
        <fieldset disabled={checkingSafety} className="contents">

        {/* Voice input */}
        <VoiceInput
          key={currentQuestion.id}
          language={lang}
          context={voiceContext}
          disabled={checkingSafety}
          onTranscription={(text) => {
            handleAnswer(currentQuestion.id, text);
          }}
        />

        <div className="flex items-center gap-4 w-full max-w-2xl my-2">
          <div className="flex-1 h-px bg-gray-200" />
          <span className="text-sm text-gray-400">or</span>
          <div className="flex-1 h-px bg-gray-200" />
        </div>

        {currentQuestion.type === "single_select" && currentQuestion.options && (
          <div className="flex flex-wrap gap-4 justify-center max-w-3xl">
            {currentQuestion.options.map((opt) => (
              <IconCard
                key={opt.value}
                icon={opt.icon || "✅"}
                label={opt.label[lang]}
                onSelect={() => handleAnswer(currentQuestion.id, opt.value)}
              />
            ))}
          </div>
        )}

        {currentQuestion.type === "yes_no" && (
          <div className="flex gap-6">
            <TouchButton variant="success" size="large" onClick={() => handleAnswer(currentQuestion.id, "yes")}>
              {lang === "hi" ? "हां" : "Yes"}
            </TouchButton>
            <TouchButton variant="danger" size="large" onClick={() => handleAnswer(currentQuestion.id, "no")}>
              {lang === "hi" ? "नहीं" : "No"}
            </TouchButton>
          </div>
        )}

        {currentQuestion.type === "multi_select" && currentQuestion.options && (
          <MultiSelectQuestion key={currentQuestion.id} question={currentQuestion} lang={lang} onConfirm={(vals) => handleAnswer(currentQuestion.id, vals)} />
        )}

        {currentQuestion.type === "scale" && (
          <ScaleQuestion key={currentQuestion.id} lang={lang} onConfirm={(val) => handleAnswer(currentQuestion.id, val)} />
        )}
        </fieldset>
      </main>
    );
  }

  // --- Review ---
  if (step.type === "review") {
    return (
      <main className="flex min-h-dvh flex-col items-center justify-center gap-6 px-6 py-12">
        <AccessibilityControls />
        <h2 className="text-3xl font-bold text-primary">{lang === "hi" ? "आपका विवरण" : "Your Details"}</h2>
        <div className="w-full max-w-2xl space-y-4">
          {sections.map((section) => (
            <div key={section.id} className="kiosk-card">
              <h3 className="font-bold text-primary text-lg mb-2">{section.icon} {section.title[lang]}</h3>
              {section.questions.map((q) => {
                const a = answers[q.id];
                if (!a) return null;
                return (
                  <div key={q.id} className="flex justify-between py-1 border-b border-gray-100 last:border-0">
                    <span className="text-gray-600">{q.label[lang]}</span>
                    <span className="font-medium">{Array.isArray(a) ? a.join(", ") : a}</span>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
        <div className="flex gap-4">
          <TouchButton variant="secondary" size="large" onClick={() => setStep({ type: "section_intro", sectionIndex: 0 })}>
            {lang === "hi" ? "संपादित करें" : "Edit"}
          </TouchButton>
          <TouchButton variant="success" size="large" onClick={() => void submitCase()}>
            {lang === "hi" ? "जमा करें" : "Submit"}
          </TouchButton>
        </div>
        {submitError && <p className="rounded-xl border-2 border-red-500 bg-red-50 p-4 font-bold text-red-700" role="alert">{submitError}</p>}
      </main>
    );
  }

  // --- Submitting ---
  if (step.type === "submitting") {
    return (
      <main className="flex min-h-dvh flex-col items-center justify-center gap-6 px-6">
        <div className="text-6xl animate-pulse">⏳</div>
        <p className="text-2xl text-primary font-semibold">{lang === "hi" ? "जमा हो रहा है..." : "Submitting..."}</p>
      </main>
    );
  }

  // --- Done ---
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-6 px-6">
      <div className="text-6xl">✅</div>
      <h2 className="text-3xl font-bold text-primary">{lang === "hi" ? "धन्यवाद!" : "Thank You!"}</h2>
      <p className="text-xl text-gray-600">{lang === "hi" ? "आपका विवरण दर्ज हो गया है। कृपया डॉक्टर से मिलें।" : "Your details have been recorded. Please meet the doctor."}</p>
      <TouchButton variant="primary" size="large" onClick={() => router.push("/")}>
        {lang === "hi" ? "होम" : "Home"}
      </TouchButton>
    </main>
  );
}

// --- Sub-components ---

function MultiSelectQuestion({ question, lang, onConfirm }: { question: Question; lang: "hi" | "en"; onConfirm: (vals: string[]) => void }) {
  const [selected, setSelected] = useState<string[]>([]);

  const toggle = (val: string) => {
    setSelected((prev) =>
      val === "none" ? ["none"] : prev.includes(val) ? prev.filter((v) => v !== val) : [...prev.filter((v) => v !== "none"), val]
    );
  };

  return (
    <>
      <div className="flex flex-wrap gap-3 justify-center max-w-3xl">
        {question.options?.map((opt) => (
          <button
            key={opt.value}
            onClick={() => toggle(opt.value)}
            className={`px-6 py-4 rounded-xl border-2 text-lg font-medium transition min-h-[56px]
              ${selected.includes(opt.value) ? "border-accent bg-accent/10 text-accent" : "border-gray-200 bg-white text-primary"}`}
          >
            {opt.label[lang]}
          </button>
        ))}
      </div>
      <TouchButton variant="success" size="large" onClick={() => onConfirm(selected)} disabled={selected.length === 0}>
        {lang === "hi" ? "अगला" : "Next"}
      </TouchButton>
    </>
  );
}

function ScaleQuestion({ lang, onConfirm }: { lang: "hi" | "en"; onConfirm: (val: string) => void }) {
  const [value, setValue] = useState(5);

  return (
    <>
      <div className="text-6xl font-bold text-primary">{value}</div>
      <input
        type="range"
        min="1"
        max="10"
        value={value}
        onChange={(e) => setValue(parseInt(e.target.value))}
        className="w-full max-w-md h-3 bg-gray-200 rounded-lg appearance-none cursor-pointer"
        aria-label="Pain scale"
      />
      <div className="flex justify-between w-full max-w-md text-sm text-gray-500">
        <span>{lang === "hi" ? "हल्का" : "Mild"}</span>
        <span>{lang === "hi" ? "बहुत ज्यादा" : "Severe"}</span>
      </div>
      <TouchButton variant="success" size="large" onClick={() => onConfirm(String(value))}>
        {lang === "hi" ? "अगला" : "Next"}
      </TouchButton>
    </>
  );
}
