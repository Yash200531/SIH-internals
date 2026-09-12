# Speech Service

Streams approved AI4Bharat/Bhashini-compatible ASR and Indic/Bhashini-compatible TTS behind task-level APIs. Preserves language, timestamps and confidence, and supports explicit cancellation and manual fallback.

Raw audio remains in encrypted object storage when retention is authorized; Kafka carries only job metadata and object references.
