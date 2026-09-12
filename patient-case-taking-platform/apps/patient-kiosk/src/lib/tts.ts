const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const TTS_REQUEST_TIMEOUT_MS = 190_000;
const TTS_CACHE_ENTRIES = 32;
const audioCache = new Map<string, Promise<Blob>>();

async function requestPrompt(
  text: string,
  language: "hi" | "en",
): Promise<Blob> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}/api/v1/tts/synthesize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, language, voice: "calm" }),
      signal: AbortSignal.timeout(TTS_REQUEST_TIMEOUT_MS),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "TimeoutError") {
      throw new Error("Voice generation timed out. Please try a shorter prompt.");
    }
    throw new Error("Voice service could not be reached.");
  }
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail || "Voice is temporarily unavailable.");
  }
  if (!response.headers.get("content-type")?.startsWith("audio/wav")) {
    throw new Error("Voice service returned an invalid audio type.");
  }
  return response.blob();
}

export function synthesizePrompt(
  text: string,
  language: "hi" | "en",
): Promise<Blob> {
  const key = `${language}:${text.trim()}`;
  const cached = audioCache.get(key);
  if (cached) return cached;

  const request = requestPrompt(text, language);
  audioCache.set(key, request);
  if (audioCache.size > TTS_CACHE_ENTRIES) {
    const oldest = audioCache.keys().next().value;
    if (oldest) audioCache.delete(oldest);
  }
  void request.catch(() => {
    if (audioCache.get(key) === request) audioCache.delete(key);
  });
  return request;
}

export function prefetchPrompt(text: string, language: "hi" | "en"): void {
  void synthesizePrompt(text, language).catch(() => undefined);
}
