# Phase 7 approval record

**Decision state:** Pending — engineering candidate only  
**Last updated:** 2026-09-04

No approval is implied by implemented code, passing tests, or this document.
Each owner must record their name, decision, date, evidence reviewed and any
conditions before the corresponding gate can be considered closed.

| Gate | Required owner | Evidence required | Status |
| --- | --- | --- | --- |
| Clinical safety | Clinical-safety owner | Hazard log; representative extraction/OCR results; false-accept and material-error review; manual fallback; downstream wording | Pending |
| Privacy and security | Privacy/security owner | Purpose and consent flow; threat model; RLS/role grants; private object policy; retention/deletion/legal hold; event/log PHI review | Pending |
| Accessibility | Accessibility owner | Keyboard and screen-reader review; bilingual comprehension; source zoom/highlight; error and outage recovery | Pending |
| Facility operations | Facility operations owner | Queue staffing; rescan/manual-entry workflow; malware escalation; downtime procedure; rollback and recovery drills | Pending |
| Engineering | Engineering owner | CI/static checks; live integration; migration/rollback plan; dependency and container review; SLO instrumentation | Pending final review |

## Evidence available in this repository

- [`../plans/PHASE-7-DOCUMENT-INGESTION-OCR.md`](../plans/PHASE-7-DOCUMENT-INGESTION-OCR.md)
- [`../safety/PHASE-7-HAZARD-LOG.md`](../safety/PHASE-7-HAZARD-LOG.md)
- [`../../tests/model-evaluations/phase7/PROVENANCE.md`](../../tests/model-evaluations/phase7/PROVENANCE.md)
- [`../../tests/model-evaluations/phase7/candidate-report.json`](../../tests/model-evaluations/phase7/candidate-report.json)
- [`../../infrastructure/runbooks/PHASE-7-DOCUMENT-PIPELINE.md`](../../infrastructure/runbooks/PHASE-7-DOCUMENT-PIPELINE.md)

## Evidence still required outside the repository

- A governed, representative prescription/OCR evaluation dataset with permitted
  use, adjudication protocol and facility/language/capture strata.
- Owner-approved release thresholds recorded before running the release
  evaluation; the checked-in null thresholds are deliberate.
- Real browser accessibility/usability sessions with nurses and doctors.
- Staging Kafka/object/Mongo/PostgreSQL outage, replay, backup/restore and
  rollback drills on the intended deployment topology.
- Production service identities, least-privilege grants, TLS/secrets, retention,
  deletion, legal-hold and incident-response evidence.

## Approval entries

Record approvals below without rewriting the evidence history.

| Owner role | Name | Decision | Date | Evidence reference / conditions |
| --- | --- | --- | --- | --- |
| Clinical safety | — | Pending | — | — |
| Privacy/security | — | Pending | — | — |
| Accessibility | — | Pending | — | — |
| Facility operations | — | Pending | — | — |
| Engineering | — | Pending | — | — |
