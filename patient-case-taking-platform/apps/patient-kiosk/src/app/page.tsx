"use client";

import { useState } from "react";
import Link from "next/link";
import { AccessibilityControls } from "@/components/AccessibilityControls";

const COPY = {
  hi: {
    eyebrow: "आपकी बात, आपकी भाषा में",
    title: "अपनी सेहत की बात",
    titleAccent: "आसानी से बताइए।",
    lede: "बोलकर या छूकर शुरू करें। MediKiosk आपकी बात समझने में मदद करेगा और हर उत्तर आपसे पक्का करेगा।",
    voiceTitle: "नमस्ते, मैं सुनने के लिए तैयार हूँ",
    voiceHelp: "माइक दबाकर अपनी परेशानी बताइए — जैसे “मुझे दो दिन से बुखार है।”",
    speak: "बोलकर शुरू करें",
    stop: "सुनना रोकें",
    touch: "छूकर शुरू करें",
    helper: "सहायता चाहिए? नर्स को बुलाएँ",
  },
  en: {
    eyebrow: "Your story, in your language",
    title: "Tell us how you feel.",
    titleAccent: "We’ll listen carefully.",
    lede: "Speak or tap to begin. MediKiosk helps organize your story and asks you to confirm every answer.",
    voiceTitle: "Namaste, I’m ready to listen",
    voiceHelp: "Press the microphone and describe your concern — for example, “I have had a fever for two days.”",
    speak: "Start with voice",
    stop: "Stop listening",
    touch: "Start by touch",
    helper: "Need help? Call a nurse",
  },
};

export default function Home() {
  const [lang, setLang] = useState<"hi" | "en">("hi");
  const copy = COPY[lang];

  return (
    <main className="patient-shell">
      <header className="patient-header">
        <div className="mk-wordmark" aria-label="MediKiosk">Medi<em>Kiosk</em></div>
        <p className="patient-trust">Ayushman Bharat Digital Mission ready · सुरक्षित सत्र</p>
        <AccessibilityControls />
      </header>

      <div className="patient-main">
        <section className="patient-copy mk-enter">
          <p className="mk-eyebrow">{copy.eyebrow}</p>
          <h1 className="mk-display patient-title">{copy.title}<span>{copy.titleAccent}</span></h1>
          <p className="patient-lede">{copy.lede}</p>
          <div className="patient-language" aria-label="Choose language">
            <button className="language-chip" aria-pressed={lang === "hi"} onClick={() => setLang("hi")}>अ हिंदी</button>
            <button className="language-chip" aria-pressed={lang === "en"} onClick={() => setLang("en")}>A English</button>
          </div>
        </section>

        <section className="mk-card patient-card mk-enter" aria-live="polite">
          <span className="mk-pill mk-pill--success">● निजी और सुरक्षित · Private & secure</span>
          <Link
            className="voice-orb"
            href="/kiosk-session"
            aria-label={copy.speak}
          >
            ●
          </Link>
          <h2 className="voice-title">{copy.voiceTitle}</h2>
          <p className="voice-help">{copy.voiceHelp}</p>
          <div className="patient-actions">
            <Link className="mk-button mk-button--success" href="/kiosk-session">{copy.speak} <span aria-hidden="true">→</span></Link>
            <Link className="mk-button mk-button--soft" href="/case-taking">{copy.touch}</Link>
            <Link className="mk-button mk-button--soft" href="/records">Records · रिकॉर्ड</Link>
            <Link className="mk-button mk-button--soft" href="/consents">Consent · सहमति</Link>
          </div>
          <p className="patient-note"><span aria-hidden="true">✦</span>{copy.helper}</p>
        </section>
      </div>
    </main>
  );
}
