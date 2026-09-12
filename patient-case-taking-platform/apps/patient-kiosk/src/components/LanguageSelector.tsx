"use client";

import { useState } from "react";

const LANGUAGES = [
  { code: "hi", label: "हिन्दी" },
  { code: "en", label: "English" },
  { code: "mr", label: "मराठी" },
  { code: "ta", label: "தமிழ்" },
  { code: "bn", label: "বাংলা" },
  { code: "te", label: "తెలుగు" },
  { code: "kn", label: "ಕನ್ನಡ" },
  { code: "gu", label: "ગુજરાતી" },
];

interface LanguageSelectorProps {
  onSelect: (lang: string) => void;
  currentLang: string;
}

export function LanguageSelector({ onSelect, currentLang }: LanguageSelectorProps) {
  const [selected, setSelected] = useState(currentLang);

  return (
    <select
      aria-label="Select language"
      value={selected}
      onChange={(e) => {
        setSelected(e.target.value);
        onSelect(e.target.value);
      }}
      className="rounded-lg border-2 border-primary px-4 py-3 text-lg focus:outline-none focus:ring-2 focus:ring-accent"
    >
      {LANGUAGES.map((lang) => (
        <option key={lang.code} value={lang.code}>
          {lang.label}
        </option>
      ))}
    </select>
  );
}
