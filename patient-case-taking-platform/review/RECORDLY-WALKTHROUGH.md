# Final workflow recording checklist

Status: Recording cancelled by the user ("skip recording"). The following is historical preparation only; project implementation continues.

Requested deliverable: Recordly screen recording of the completed workflow and
all dashboards/features, following the final project review. This checklist is
preparation, not evidence that the recording or outstanding features are done.

Installed recorder discovered at `C:\Program Files\Recordly\Recordly.exe`.
Installed updater metadata identifies `webadderall/Recordly`. Recorder controls,
capture permissions, export and output location still need verification.

Use synthetic local patients only. Do not display environment files, credentials,
provider tokens, personal browser tabs or other desktop applications. Label the
demonstration as an engineering showcase. Do not imply clinical validation,
staff receipt of broker events or production provider verification.

Required walkthrough coverage, to reconcile with the remaining plan audit:

- Patient entry, language/accessibility controls, session creation and consent.
- Touch intake and voice intake, transcript correction/confirmation, failure
  fallback, urgent-symptom interruption and accepted intake submission.
- Document upload, scanning/processing, source preview, OCR review/correction,
  promotion and patient-visible reviewed facts.
- Nurse worklist, alert review/acknowledgment and clinician handoff.
- Doctor draft generation, evidence review, corrections, review submission and
  signing; demonstrate that patients see only signed summaries.
- Patient records, report detail/download, longitudinal timeline and consent
  review/revocation.
- Clinical search, filters, timeline and CSV export with appropriate access.
- Administration dashboard and every implemented control identified in its audit.
- Session ending and shared-device cleanup.

Before capture: finish the feature/service audit, fix failures, verify each scene
against live synthetic state, prepare a resettable scenario and start Recordly.
After capture: export a playable video, inspect beginning/middle/end and verify
that the feature coverage matches the recording. Record the exact output path,
duration, omissions and verification evidence here. TTS and HiMed 8B are excluded.

## Recording-first request — 10 September

User explicitly prioritized capturing the current full workflow before further
implementation. Code changes paused. Started local infrastructure and current
source API (8000), patient (3000), clinician (3001), admin (3002) servers.
Recordly is installed but no native app control or recording tool is exposed.
Browser automation repeatedly timed out, then failed with a Windows sandbox
`apply deny-read ACLs` error. No recording was started and no video exists from
this attempt. Browser control must be restored and Recordly capture started
manually or through an available supported control before a walkthrough can be
recorded. This recording-first request was subsequently cancelled by the user.
Admin overview currently uses static counters: show its actual limitations in
any current-state recording rather than claim live administration functionality.

Browser control recovered on the next check. Patient start screen is visible in
Codex in-app browser tab 3 and retained for handoff. All three dashboards, patient
session entry, clinical login/worklist and API docs responded HTTP 200. Recordly
still has no exposed native capture controls; user was asked to start capture of
the dashboard window and reply "Recording started". Await that reply before
performing the walkthrough. No recording has been confirmed or produced.
