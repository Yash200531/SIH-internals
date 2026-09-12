"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { synthesizePrompt } from "../lib/tts";
import { TouchButton } from "./TouchButton";

interface AudioPromptProps {
  text: string;
  audioSrc?: string;
  language?: "hi" | "en";
  autoPlay?: boolean;
  onPlay?: () => void;
}

export function AudioPrompt({
  text,
  audioSrc,
  language = "hi",
  autoPlay = false,
  onPlay,
}: AudioPromptProps) {
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [generatedAudio, setGeneratedAudio] = useState<{ key: string; src: string } | null>(null);
  const [volume, setVolume] = useState(0.8);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const pendingPlayRef = useRef(false);
  const autoplayedTextRef = useRef("");
  const requestKey = `${language}:${text}`;
  const generatedSrc = generatedAudio?.key === requestKey ? generatedAudio.src : "";
  const resolvedSrc = audioSrc || generatedSrc;

  const handlePlay = useCallback(async () => {
    setError("");
    if (resolvedSrc && audioRef.current) {
      audioRef.current.volume = volume;
      try {
        await audioRef.current.play();
        setPlaying(true);
        onPlay?.();
      } catch {
        setError(language === "hi" ? "आवाज़ नहीं चलाई जा सकी।" : "Audio could not be played.");
      }
      return;
    }

    setLoading(true);
    pendingPlayRef.current = true;
    try {
      const blob = await synthesizePrompt(text, language);
      setGeneratedAudio({ key: requestKey, src: URL.createObjectURL(blob) });
    } catch (caught) {
      pendingPlayRef.current = false;
      setError(caught instanceof Error ? caught.message : "Voice is unavailable");
    } finally {
      setLoading(false);
    }
  }, [language, onPlay, requestKey, resolvedSrc, text, volume]);

  useEffect(() => {
    if (!resolvedSrc || !pendingPlayRef.current || !audioRef.current) return;
    pendingPlayRef.current = false;
    audioRef.current.volume = volume;
    void audioRef.current
      .play()
      .then(() => {
        setPlaying(true);
        onPlay?.();
      })
      .catch(() => {
        setError(language === "hi" ? "आवाज़ नहीं चलाई जा सकी।" : "Audio could not be played.");
      });
  }, [language, onPlay, resolvedSrc, volume]);

  useEffect(() => {
    if (autoPlay && autoplayedTextRef.current !== text) {
      autoplayedTextRef.current = text;
      queueMicrotask(handlePlay);
    }
  }, [autoPlay, handlePlay, text]);

  useEffect(() => {
    return () => {
      if (generatedAudio) URL.revokeObjectURL(generatedAudio.src);
    };
  }, [generatedAudio]);

  const handleStop = () => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
    }
    setPlaying(false);
  };

  const status = error || (loading
    ? language === "hi" ? "आवाज़ बन रही है…" : "Preparing voice…"
    : language === "hi" ? "सुनने के लिए दबाएँ" : "Press to listen");

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-2xl bg-blue-50 p-4">
      <audio ref={audioRef} src={resolvedSrc || undefined} onEnded={() => setPlaying(false)} />

      <TouchButton
        variant="primary"
        size="medium"
        onClick={playing ? handleStop : handlePlay}
        disabled={loading}
        aria-label={playing ? "Stop audio" : "Play question audio"}
      >
        {loading ? "…" : playing ? "⏹" : "🔊"}
      </TouchButton>

      <div className="min-w-32 flex-1">
        <input
          type="range"
          min="0"
          max="1"
          step="0.1"
          value={volume}
          onChange={(event) => setVolume(Number(event.target.value))}
          aria-label="Volume"
          className="h-2 w-full cursor-pointer appearance-none rounded-lg bg-gray-200"
        />
      </div>

      <TouchButton
        variant="secondary"
        size="small"
        onClick={handlePlay}
        disabled={loading}
        aria-label="Replay audio"
      >
        ↻
      </TouchButton>
      <span className="w-full text-xs text-gray-600" role="status" aria-live="polite">
        {status}
      </span>
    </div>
  );
}
