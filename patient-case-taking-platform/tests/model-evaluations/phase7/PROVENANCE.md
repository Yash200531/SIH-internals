# Phase 7 synthetic evaluation provenance

All fixtures in `manifest.jsonl` are original synthetic strings created for
MediKiosk testing. They contain no patient data and are released as CC0-1.0.
Names are medication names, not people. Dates and identifiers are invented.

The set covers the currently supported `prescription` class across English,
Hindi/Devanagari and Hindi written in Latin script, plus clean, degraded and
glare-labelled synthetic capture conditions. The labels describe intended test
strata; they are not evidence that a camera/OCR model was evaluated under those
physical conditions.

This frozen set measures deterministic extraction and source-link retention
from supplied OCR regions. It does not measure real OCR accuracy, handwriting,
camera capture, lab tables or clinical outcome safety. Adding or changing a
fixture requires a manifest version bump and independent clinical review.
