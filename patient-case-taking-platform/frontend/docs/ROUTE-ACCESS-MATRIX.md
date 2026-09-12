# Route and Access Matrix

Exact URL names can change during UX design; capability separation should not.

| Application | Route group | Allowed roles | Purpose |
|---|---|---|---|
| User Admin | `/users` | User admin | Create, suspend and restore workforce accounts |
| User Admin | `/roles` | Security admin | Assign approved roles and facility scope |
| User Admin | `/facilities` | Platform/facility admin | Manage facility associations |
| User Admin | `/audit` | Privacy/audit reviewer | Review access and policy evidence |
| Doctor | `/worklist` | Doctor, nurse | Assigned and waiting encounters |
| Doctor | `/patients/:id` | Authorized care team | Patient clinical context |
| Doctor | `/encounters/:id/review` | Doctor, permitted nurse | Review confirmed case-taking data |
| Doctor | `/encounters/:id/note` | Doctor | Edit and sign clinical note |
| Doctor | `/alerts` | Clinical roles | Review deterministic clinical/workflow alerts |
| Patient | `/onboarding` | Patient/caregiver | Language, accessibility and session setup |
| Patient | `/identity` | Patient/caregiver/operator | Registration and identity linking |
| Patient | `/case-taking/:id` | Patient/delegate | Voice/text structured interview |
| Patient | `/records` | Patient/delegate with consent | View patient-friendly records |
| Patient | `/consents` | Patient/authorized delegate | Grant, review and revoke consent |
| Patient | `/caregivers` | Patient | Manage delegated access |

## Cross-role restrictions

- Administration roles do not automatically receive clinical record access.
- Support impersonation is prohibited; controlled assisted access must be attributed and audited.
- Caregivers use delegated identities and never share the patient's credentials.
- Clinical break-glass access is time-bound, reason-bound and separately audited.

