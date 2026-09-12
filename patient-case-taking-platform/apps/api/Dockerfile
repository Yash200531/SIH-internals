FROM python:3.11-slim AS base

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY migrations ./migrations
COPY tools ./tools

RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Opt-in speech image; ordinary API workers do not need model dependencies.
FROM base AS asr
USER root
RUN apt-get update && apt-get install -y --no-install-recommends libsndfile1 \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
RUN pip install --no-cache-dir '.[ai-asr,voice-platform]'
USER appuser

# Opt-in IndicF5 image. This deliberately contains TTS only; ASR and LLM must
# remain on their mock providers on a 6 GB GPU so models do not compete for VRAM.
FROM base AS tts
USER root
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg git libsndfile1 \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
      torch==2.7.1 torchaudio==2.7.1 \
      --index-url https://download.pytorch.org/whl/cu128 \
    && pip install --no-cache-dir '.[ai-tts-f5]'
USER appuser

FROM base AS runtime
