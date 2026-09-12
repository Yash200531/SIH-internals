"use client";

import { useState, useEffect } from "react";

interface AccessibilityState {
  largeText: boolean;
  highContrast: boolean;
}

export function AccessibilityControls() {
  const [settings, setSettings] = useState<AccessibilityState>({
    largeText: false,
    highContrast: false,
  });

  useEffect(() => {
    document.documentElement.classList.toggle("a11y-large-text", settings.largeText);
    document.documentElement.classList.toggle("a11y-high-contrast", settings.highContrast);
    localStorage.setItem("medikiosk-a11y", JSON.stringify(settings));
  }, [settings]);

  useEffect(() => {
    const saved = localStorage.getItem("medikiosk-a11y");
    if (!saved) return;
    try {
      const parsed = JSON.parse(saved) as AccessibilityState;
      queueMicrotask(() => setSettings(parsed));
    } catch {
      localStorage.removeItem("medikiosk-a11y");
    }
  }, []);

  const toggle = (key: keyof AccessibilityState) =>
    setSettings((s) => ({ ...s, [key]: !s[key] }));

  return (
    <div className="fixed top-4 right-4 z-50 flex flex-col gap-2">
      <button
        onClick={() => toggle("largeText")}
        aria-pressed={settings.largeText}
        aria-label="Toggle large text"
        className={`w-[44px] h-[44px] rounded-lg border-2 text-lg font-bold transition
          ${settings.largeText ? "bg-primary text-white border-primary" : "bg-white text-primary border-gray-300"}`}
      >
        A+
      </button>
      <button
        onClick={() => toggle("highContrast")}
        aria-pressed={settings.highContrast}
        aria-label="Toggle high contrast"
        className={`w-[44px] h-[44px] rounded-lg border-2 text-lg font-bold transition
          ${settings.highContrast ? "bg-black text-white border-black" : "bg-white text-primary border-gray-300"}`}
      >
        ◐
      </button>
    </div>
  );
}
