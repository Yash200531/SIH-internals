# Conversation Orchestrator

Runs deterministic interview state machines and coordinates AI4Bharat/Bhashini-compatible ASR, PyTorch clinical NLP, versioned Python safety rules, the AI gateway and Indic/Bhashini-compatible TTS. It persists confirmed answers through the FastAPI clinical platform.

WebSockets carry partial transcripts and progress to authorized clients. PostgreSQL-backed workflow changes and Kafka events remain the durable record; WebSocket delivery is never authoritative.
