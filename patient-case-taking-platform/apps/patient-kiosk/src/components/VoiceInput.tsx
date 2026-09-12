"use client";

import { useEffect, useRef, useState } from "react";
import { TouchButton } from "./TouchButton";
import { useVoiceRecorder } from "@/hooks/useVoiceRecorder";
import { useASR } from "@/hooks/useASR";
import { MicrophoneDiagnostics } from "./MicrophoneDiagnostics";

interface VoiceContext {
  tenantId: string;
  sessionId: string;
  encounterId: string;
  consentId: string;
  retainAudio: boolean;
  audioRetentionConsent: boolean;
}

interface VoiceInputProps {
  language?: "hi" | "en";
  context: VoiceContext;
  onTranscription: (text: string, confidence: number | null) => void;
  disabled?: boolean;
}

export function VoiceInput({
  language = "hi",
  context,
  onTranscription,
  disabled = false,
}: VoiceInputProps) {
  const [mode, setMode] = useState<"idle" | "recording" | "processing" | "review">("idle");
  const [draftTranscript, setDraftTranscript] = useState("");
  const [deviceId, setDeviceId] = useState("");
  const [audioLevel, setAudioLevel] = useState(0);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const animFrameRef = useRef<number>(0);
  const ctxRef = useRef<AudioContext | null>(null);
  const deliveredTranscriptRef = useRef("");

  const {
    isRecording,
    isSupported,
    stream,
    startRecording,
    stopRecording,
    cancelRecording,
    error: recordError,
  } = useVoiceRecorder({ language, deviceId });

  const {
    transcript,
    interimTranscript,
    confidence,
    needsClarification,
    signalQuality,
    isListening,
    error: asrError,
    connect,
    disconnect,
    sendAudio,
    endAudio,
    reset,
  } = useASR({ language, context });

  // Audio level visualization — uses the real stream
  useEffect(() => {
    if (isRecording && stream) {
      const ctx = new AudioContext();
      ctxRef.current = ctx;
      const source = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);
      analyserRef.current = analyser;

      const updateLevel = () => {
        const data = new Uint8Array(analyser.frequencyBinCount);
        analyser.getByteFrequencyData(data);
        const avg = data.reduce((a, b) => a + b, 0) / data.length;
        setAudioLevel(avg / 255);
        animFrameRef.current = requestAnimationFrame(updateLevel);
      };
      updateLevel();

      return () => {
        cancelAnimationFrame(animFrameRef.current);
        ctx.close();
      };
    }
  }, [isRecording, stream]);

  // Stream audio chunks to ASR
  useEffect(() => {
    if (!isRecording || !stream) return;

    const ctx = ctxRef.current;
    if (!ctx) return;

    const source = ctx.createMediaStreamSource(stream);
    const processor = ctx.createScriptProcessor(4096, 1, 1);

    processor.onaudioprocess = (e) => {
      const channelData = e.inputBuffer.getChannelData(0);
      const samples = downsample(channelData, ctx.sampleRate, 16000);
      sendAudio(encodePCM16(samples));
    };

    source.connect(processor);
    processor.connect(ctx.destination);

    return () => {
      source.disconnect();
      processor.disconnect();
    };
  }, [isRecording, stream, sendAudio]);

  // Handle transcription result
  useEffect(() => {
    if (transcript && !isListening && transcript !== deliveredTranscriptRef.current) {
      deliveredTranscriptRef.current = transcript;
      setDraftTranscript(transcript);
      setMode("review");
    }
  }, [isListening, transcript]);

  const error = recordError || asrError;
  useEffect(() => {
    if (error) {
      queueMicrotask(() => {
        cancelRecording();
        setMode("idle");
        disconnect();
      });
    }
  }, [cancelRecording, disconnect, error]);

  const handleStart = async () => {
    reset();
    deliveredTranscriptRef.current = "";
    setAudioLevel(0);
    setMode("recording");
    try {
      connect();
      await startRecording();
    } catch {
      disconnect();
      setMode("idle");
    }
  };

  const handleStop = async () => {
    setMode("processing");
    try {
      await stopRecording();
      endAudio();
    } catch {
      setMode("idle");
      disconnect();
    }
  };

  const handleCancel = () => {
    cancelRecording();
    disconnect();
    reset();
    setMode("idle");
    setAudioLevel(0);
  };

  if (!isSupported) {
    return (
      <div className="text-center text-gray-500 text-sm p-4">
        🎤 Microphone not available. Use touch to answer.
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center gap-4" aria-busy={mode === "processing"}>
      {error && (
        <div className="text-red-600 text-sm bg-red-50 px-4 py-2 rounded-lg" role="alert">
          {error}
        </div>
      )}

      {mode === "idle" && (
        <>
          <MicrophoneDiagnostics language={language} onDeviceChange={setDeviceId} />
          <TouchButton
            variant="primary"
            size="large"
            onClick={handleStart}
            disabled={disabled}
            aria-label="Start voice input"
          >
            🎤 {language === "hi" ? "उत्तर बोलें" : "Speak Answer"}
          </TouchButton>
        </>
      )}

      {mode === "recording" && (
        <div className="flex flex-col items-center gap-4" role="status" aria-live="polite" aria-label={language === "hi" ? "माइक्रोफ़ोन सुन रहा है" : "Microphone is listening"}>
          <div className="flex items-end gap-1 h-12">
            {[...Array(5)].map((_, i) => (
              <div
                key={i}
                className="w-3 bg-red-500 rounded-full transition-all duration-100"
                style={{
                  height: `${Math.max(8, audioLevel * 48 * (1 + i * 0.2))}px`,
                }}
              />
            ))}
          </div>

          {interimTranscript && (
            <div className="text-lg text-gray-600 italic max-w-md text-center">
              {interimTranscript}
            </div>
          )}

          <div className="flex gap-4">
            <TouchButton
              variant="danger"
              size="medium"
              onClick={handleCancel}
              aria-label="Cancel recording"
            >
              ✕
            </TouchButton>
            <TouchButton
              variant="success"
              size="large"
              onClick={handleStop}
              aria-label="Stop recording"
              className="animate-pulse"
            >
              ⏹ Stop
            </TouchButton>
          </div>

          <p className="text-sm text-gray-500">
            {language === "hi" ? "बोलें..." : "Speak now..."}
          </p>
        </div>
      )}

      {mode === "processing" && (
        <div className="flex flex-col items-center gap-2" role="status" aria-live="polite">
          <div className="text-3xl animate-spin">⏳</div>
          <p className="text-sm text-gray-600">
            {language === "hi" ? "प्रसंस्करण..." : "Processing..."}
          </p>
        </div>
      )}

      {mode === "review" && (
        <div className="w-full max-w-xl space-y-3 rounded-2xl border border-blue-200 bg-blue-50 p-4" role="group" aria-labelledby="voice-review-title">
          <p className="font-semibold text-primary" id="voice-review-title">
            {needsClarification
              ? language === "hi"
                ? "आवाज़ स्पष्ट नहीं थी। कृपया सुधारें या फिर बोलें।"
                : "The audio was unclear. Correct it or try again."
              : language === "hi"
                ? "क्या हमने सही सुना?"
                : "Did we hear that correctly?"}
          </p>
          {signalQuality !== null && (
            <p className="text-xs text-gray-500">
              {language === "hi" ? "ध्वनि गुणवत्ता" : "Signal quality"}: {Math.round(signalQuality * 100)}%
            </p>
          )}
          <textarea
            value={draftTranscript}
            onChange={(event) => setDraftTranscript(event.target.value)}
            className="min-h-28 w-full rounded-xl border border-gray-300 bg-white p-3 text-lg"
            aria-label={language === "hi" ? "लिखित उत्तर सुधारें" : "Correct transcript"}
          />
          <div className="flex flex-wrap justify-center gap-3">
            <TouchButton
              variant="secondary"
              size="medium"
              onClick={() => {
                reset();
                setDraftTranscript("");
                setMode("idle");
              }}
            >
              {language === "hi" ? "फिर से बोलें" : "Try again"}
            </TouchButton>
            <TouchButton
              variant="success"
              size="medium"
              disabled={!draftTranscript.trim()}
              onClick={() => onTranscription(draftTranscript.trim(), confidence)}
            >
              {language === "hi" ? "पुष्टि करें" : "Confirm"}
            </TouchButton>
          </div>
        </div>
      )}

      <p className="text-xs text-gray-400">
        {language === "hi"
          ? "या नीचे टैप करके उत्तर दें"
          : "Or tap below to answer"}
      </p>
    </div>
  );
}

function downsample(samples: Float32Array, sourceRate: number, targetRate: number): Float32Array {
  if (sourceRate === targetRate) return samples;
  const ratio = sourceRate / targetRate;
  const output = new Float32Array(Math.floor(samples.length / ratio));
  for (let i = 0; i < output.length; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(samples.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j++) sum += samples[j];
    output[i] = sum / Math.max(1, end - start);
  }
  return output;
}

function encodePCM16(samples: Float32Array): Blob {
  const buffer = new ArrayBuffer(samples.length * 2);
  const view = new DataView(buffer);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buffer], { type: "application/octet-stream" });
}
