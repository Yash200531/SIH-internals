"use client";

import { useState } from "react";
import Link from "next/link";
import { grantPatientConsent, readPatientSession } from "../../lib/patientPortal";

const translations = {
  en: {
    title: "Consent to Share Information",
    subtitle: "We need your permission to collect and share your health information.",
    purpose_label: "Purpose of data collection",
    purpose_text:
      "To help your doctor understand your health condition and provide appropriate treatment.",
    scope_label: "What information will be shared",
    scope_items: [
      "Your name and basic details",
      "Your health complaint and symptoms",
      "Your medical history",
      "Any medications you are taking",
    ],
    recipient_label: "Who will see this information",
    recipient_text: "Only the doctor and clinical staff involved in your care.",
    rights_label: "Your rights",
    rights_items: [
      "You can withdraw consent at any time",
      "Your information will not be shared without your permission",
      "You can request a copy of your records",
    ],
    grant_button: "I Give My Consent",
    deny_button: "I Do Not Consent",
    emergency_note:
      "In a medical emergency, we may share information without consent to protect your life.",
    confirmation_title: "Please confirm",
    confirmation_text:
      "You are about to give consent for sharing your health information. Is this correct?",
    confirm_yes: "Yes, I consent",
    confirm_no: "Go back",
  },
  hi: {
    title: "जानकारी साझा करने की सहमति",
    subtitle: "हमें आपकी स्वास्थ्य जानकारी एकत्र करने और साझा करने की अनुमति चाहिए।",
    purpose_label: "डेटा एकत्र करने का उद्देश्य",
    purpose_text:
      "आपके डॉक्टर को आपकी स्वास्थ्य स्थिति को समझने और उपयुक्त उपचार प्रदान करने में मदद करने के लिए।",
    scope_label: "कौन सी जानकारी साझा की जाएगी",
    scope_items: [
      "आपका नाम और बुनियादी विवरण",
      "आपकी स्वास्थ्य शिकायत और लक्षण",
      "आपका चिकित्सा इतिहास",
      "आप जो भी दवाइयां ले रहे हैं",
    ],
    recipient_label: "इस जानकारी कौन देखेगा",
    recipient_text: "केवल आपकी देखभाल में शामिल डॉक्टर और नैदानिक कर्मचारी।",
    rights_label: "आपके अधिकार",
    rights_items: [
      "आप किसी भी समय सहमति वापस ले सकते हैं",
      "आपकी अनुमति के बिना आपकी जानकारी साझा नहीं की जाएगी",
      "आप अपने रिकॉर्ड की प्रतिलिपि का अनुरोध कर सकते हैं",
    ],
    grant_button: "मैं अपनी सहमति देता हूं",
    deny_button: "मैं सहमत नहीं हूं",
    emergency_note:
      "चिकित्सा आपातकाल में, हम आपकी जान बचाने के लिए बिना सहमति के जानकारी साझा कर सकते हैं।",
    confirmation_title: "कृपया पुष्टि करें",
    confirmation_text:
      "आप अपनी स्वास्थ्य जानकारी साझा करने की सहमति देने वाले हैं। क्या यह सही है?",
    confirm_yes: "हां, मैं सहमत हूं",
    confirm_no: "वापस जाएं",
  },
};

export default function ConsentPage() {
  const [lang, setLang] = useState<"en" | "hi">("hi");
  const [step, setStep] = useState<"consent" | "confirm" | "granted" | "denied">("consent");
  const [retainAudio, setRetainAudio] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const t = translations[lang];

  const handleGrant = () => setStep("confirm");
  const handleConfirm = async () => {
    const session = readPatientSession();
    const encounterId = localStorage.getItem("notmid-encounter-id");
    if (!session || !encounterId) {
      setError(lang === "hi" ? "सुरक्षित सत्र नहीं मिला। कृपया फिर से शुरू करें।" : "Secure session not found. Please start again.");
      setStep("consent");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const consent = await grantPatientConsent(session, encounterId, retainAudio);
      localStorage.setItem("notmid-consent-id", consent.id);
      localStorage.setItem("notmid-retain-audio", String(retainAudio));
      localStorage.setItem("notmid-language", lang);
      setStep("granted");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Consent could not be saved");
      setStep("consent");
    } finally {
      setBusy(false);
    }
  };
  const handleDeny = () => {
    localStorage.removeItem("notmid-consent-id");
    localStorage.setItem("notmid-retain-audio", "false");
    setStep("denied");
  };

  if (step === "granted") {
    return (
      <div className="min-h-screen bg-white flex items-center justify-center p-8">
        <div className="max-w-md text-center">
          <div className="text-6xl mb-6">✅</div>
          <h1 className="text-2xl font-bold text-primary mb-4">
            {lang === "hi" ? "सहमति दी गई" : "Consent Granted"}
          </h1>
          <p className="text-gray-600 mb-8">
            {lang === "hi"
              ? "आपकी सहमति दर्ज की गई है। कृपया अपनी शिकायत दर्ज करने के लिए अगला बटन दबाएं।"
              : "Your consent has been recorded. Please press Next to begin describing your complaint."}
          </p>
          <a
            href="/case-taking"
            className="inline-block bg-primary text-white px-8 py-4 rounded-lg text-lg font-semibold hover:bg-primary/90 transition"
          >
            {lang === "hi" ? "अगला" : "Next"}
          </a>
        </div>
      </div>
    );
  }

  if (step === "denied") {
    return (
      <div className="min-h-screen bg-white flex items-center justify-center p-8">
        <div className="max-w-md text-center">
          <div className="text-6xl mb-6">❌</div>
          <h1 className="text-2xl font-bold text-red-600 mb-4">
            {lang === "hi" ? "सहमति नहीं दी गई" : "Consent Not Granted"}
          </h1>
          <p className="text-gray-600 mb-8">
            {lang === "hi"
              ? "हम आपकी जानकारी एकत्र नहीं करेंगे। यदि आप अपनी शिकायत दर्ज करना चाहते हैं, तो कृपया रिसेप्शन पर जाएं।"
              : "We will not collect your information. If you wish to register your complaint, please visit the reception desk."}
          </p>
          <Link
            href="/"
            className="inline-block border-2 border-primary text-primary px-8 py-4 rounded-lg text-lg font-semibold hover:bg-primary/5 transition"
          >
            {lang === "hi" ? "होम" : "Home"}
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-white">
      <div className="fixed top-4 right-4 z-10">
        <button
          onClick={() => setLang(lang === "en" ? "hi" : "en")}
          className="bg-gray-100 px-4 py-2 rounded-lg text-sm font-medium hover:bg-gray-200 transition"
        >
          {lang === "en" ? "हिंदी" : "English"}
        </button>
      </div>

      <div className="max-w-2xl mx-auto p-8 pt-16">
        <h1 className="text-3xl font-bold text-primary mb-2">{t.title}</h1>
        <p className="text-gray-600 mb-8">{t.subtitle}</p>
        {error && <p className="mb-6 rounded-xl border-2 border-red-500 bg-red-50 p-4 font-bold text-red-700" role="alert">{error}</p>}

        <div className="mb-8 p-6 bg-blue-50 rounded-xl">
          <h2 className="font-bold text-primary mb-2">{t.purpose_label}</h2>
          <p className="text-gray-700">{t.purpose_text}</p>
        </div>

        <div className="mb-8">
          <h2 className="font-bold text-primary mb-3">{t.scope_label}</h2>
          <ul className="space-y-2">
            {t.scope_items.map((item, i) => (
              <li key={i} className="flex items-start gap-3">
                <span className="text-accent mt-1">✓</span>
                <span className="text-gray-700">{item}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="mb-8 p-6 bg-gray-50 rounded-xl">
          <h2 className="font-bold text-primary mb-2">{t.recipient_label}</h2>
          <p className="text-gray-700">{t.recipient_text}</p>
        </div>

        <div className="mb-8">
          <h2 className="font-bold text-primary mb-3">{t.rights_label}</h2>
          <ul className="space-y-2">
            {t.rights_items.map((item, i) => (
              <li key={i} className="flex items-start gap-3">
                <span className="text-blue-500 mt-1">ℹ</span>
                <span className="text-gray-700">{item}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="mb-8 p-4 bg-yellow-50 border border-yellow-200 rounded-xl">
          <p className="text-sm text-yellow-800">⚠ {t.emergency_note}</p>
        </div>

        <label className="mb-8 flex items-start gap-4 rounded-xl border-2 border-blue-200 bg-blue-50 p-5">
          <input
            type="checkbox"
            checked={retainAudio}
            onChange={(event) => setRetainAudio(event.target.checked)}
            className="mt-1 h-6 w-6"
          />
          <span>
            <strong className="block text-primary">
              {lang === "hi" ? "आवाज़ सुरक्षित रखने की अलग सहमति" : "Separate audio-retention consent"}
            </strong>
            <span className="text-sm text-gray-700">
              {lang === "hi"
                ? "वैकल्पिक: गुणवत्ता सुधार के लिए एन्क्रिप्ट की गई रिकॉर्डिंग सीमित समय तक रखी जा सकती है। इसे न चुनने पर केवल लिखित उत्तर रहेगा।"
                : "Optional: an encrypted recording may be retained for a limited period for quality improvement. If unchecked, only the transcript is used."}
            </span>
          </span>
        </label>

        <div className="flex gap-4">
          <button
            onClick={handleGrant}
            className="flex-1 bg-accent text-white py-5 rounded-xl text-xl font-bold hover:bg-accent/90 transition min-h-[60px]"
          >
            {t.grant_button}
          </button>
          <button
            onClick={handleDeny}
            className="flex-1 border-2 border-gray-300 text-gray-600 py-5 rounded-xl text-xl font-semibold hover:bg-gray-50 transition min-h-[60px]"
          >
            {t.deny_button}
          </button>
        </div>

        {step === "confirm" && (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
            <div className="bg-white rounded-2xl p-8 max-w-md w-full shadow-2xl">
              <h2 className="text-xl font-bold mb-4">{t.confirmation_title}</h2>
              <p className="text-gray-600 mb-6">{t.confirmation_text}</p>
              <div className="flex gap-3">
                <button
                  onClick={handleConfirm}
                  disabled={busy}
                  className="flex-1 bg-accent text-white py-4 rounded-xl font-bold text-lg hover:bg-accent/90 transition"
                >
                  {busy ? (lang === "hi" ? "सहेजा जा रहा है…" : "Saving…") : t.confirm_yes}
                </button>
                <button
                  onClick={() => setStep("consent")}
                  className="flex-1 border-2 border-gray-300 py-4 rounded-xl font-semibold text-lg hover:bg-gray-50 transition"
                >
                  {t.confirm_no}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
