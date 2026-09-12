"use client";

import { useState } from "react";
import { TouchButton } from "./TouchButton";

interface MicrophoneDiagnosticsProps {
  language: "hi" | "en";
  onDeviceChange: (deviceId: string) => void;
}

export function MicrophoneDiagnostics({
  language,
  onDeviceChange,
}: MicrophoneDiagnosticsProps) {
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [status, setStatus] = useState<"idle" | "checking" | "ready" | "quiet" | "blocked">("idle");

  const runCheck = async () => {
    setStatus("checking");
    let stream: MediaStream | null = null;
    let context: AudioContext | null = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      });
      const inputs = (await navigator.mediaDevices.enumerateDevices()).filter(
        (device) => device.kind === "audioinput"
      );
      setDevices(inputs);
      if (inputs[0]) onDeviceChange(inputs[0].deviceId);

      context = new AudioContext();
      const analyser = context.createAnalyser();
      context.createMediaStreamSource(stream).connect(analyser);
      const data = new Uint8Array(analyser.frequencyBinCount);
      let peak = 0;
      const deadline = performance.now() + 1_200;
      while (performance.now() < deadline) {
        analyser.getByteTimeDomainData(data);
        peak = Math.max(peak, ...Array.from(data, (value) => Math.abs(value - 128)));
        await new Promise((resolve) => window.setTimeout(resolve, 80));
      }
      setStatus(peak >= 4 ? "ready" : "quiet");
    } catch {
      setStatus("blocked");
    } finally {
      stream?.getTracks().forEach((track) => track.stop());
      await context?.close();
    }
  };

  const labels = {
    idle: language === "hi" ? "माइक्रोफ़ोन जाँचें" : "Check microphone",
    checking: language === "hi" ? "जाँच हो रही है…" : "Checking…",
    ready: language === "hi" ? "माइक्रोफ़ोन तैयार है" : "Microphone ready",
    quiet: language === "hi" ? "आवाज़ बहुत धीमी है" : "Microphone is too quiet",
    blocked: language === "hi" ? "अनुमति नहीं मिली—टैप से उत्तर दें" : "Permission blocked—use touch",
  };

  return (
    <div className="w-full max-w-md rounded-xl border border-gray-200 bg-white p-3 text-center">
      <TouchButton
        variant="secondary"
        size="small"
        onClick={runCheck}
        disabled={status === "checking"}
      >
        {labels[status]}
      </TouchButton>
      {devices.length > 1 && (
        <select
          className="mt-3 w-full rounded-lg border p-2"
          aria-label={language === "hi" ? "माइक्रोफ़ोन चुनें" : "Select microphone"}
          onChange={(event) => onDeviceChange(event.target.value)}
        >
          {devices.map((device, index) => (
            <option key={device.deviceId} value={device.deviceId}>
              {device.label || `Microphone ${index + 1}`}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}
