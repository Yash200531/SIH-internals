# MediKiosk Product Definition

## Promise

MediKiosk helps a patient tell their story in the language and mode that feels easiest, helps a nurse act on urgent needs and complete a clean handoff, and helps a doctor review evidence before editing and signing the clinical record.

The product is calm, trustworthy, hospitable, human and recognizably Indian. The temporary brand treatment is a refined **MediKiosk** text wordmark; no logo asset is implied.

## Primary experiences

### Patient

- Bilingual Hindi/English interface with plain-language labels.
- One dominant action at a time, 56px minimum touch targets and voice-first entry.
- Visible progress, audio support and a clear path to ask a person for help.
- Critical actions use simple-language confirmation and offer recovery.

### Nurse

- Triage queue ordered by deterministic urgency and waiting time.
- Vitals at a glance, abnormal values called out with text as well as colour.
- Alerts name their rule and escalation path; AI never owns urgent escalation.
- Handoff state is explicit: not started, drafting, ready and received.

### Doctor

- Clinical review separates patient-confirmed facts, source evidence and AI-drafted text.
- Draft content remains visibly unsigned until the doctor edits and signs it.
- Contradictions and low-confidence statements stay visible rather than being silently resolved.
- Signing requires an explicit attestation and produces an auditable state change.

## Safety and privacy guardrails

- AI output is assistive and never a diagnosis, prescription or signed record.
- Kiosk pre-auth cannot search or display patient records.
- Clinical payloads and identifiers are not stored in `localStorage` or analytics.
- Demo content is synthetic and must never be replaced with production PHI in source code.
- Every critical alert requires a deterministic rule, clinical owner and escalation path.

## Success signals

- Patients can begin an intake without training and can correct what was heard.
- Nurses can identify the next urgent action and complete a handoff in seconds.
- Doctors can trace every drafted assertion to evidence before sign-off.
- All core flows remain usable with keyboard, screen reader, large text and reduced motion.
