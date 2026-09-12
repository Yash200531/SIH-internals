CREATE TABLE patient_intake_submission (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    facility_id UUID NOT NULL,
    patient_id UUID NOT NULL,
    encounter_id UUID NOT NULL,
    session_id UUID NOT NULL,
    consent_id UUID NOT NULL,
    language CHAR(2) NOT NULL CHECK (language IN ('hi', 'en')),
    chief_complaint VARCHAR(500) NOT NULL,
    confirmed_answers JSONB NOT NULL DEFAULT '{}'::JSONB,
    summary_draft JSONB NOT NULL,
    decision VARCHAR(16) NOT NULL CHECK (decision IN ('accepted', 'rejected')),
    provider VARCHAR(32) NOT NULL CHECK (provider IN ('mock', 'template-fallback')),
    idempotency_key VARCHAR(128) NOT NULL,
    request_hash_sha256 CHAR(64) NOT NULL CHECK (request_hash_sha256 ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (tenant_id, idempotency_key),
    UNIQUE (tenant_id, encounter_id),
    FOREIGN KEY (tenant_id, consent_id) REFERENCES consent_artifact (tenant_id, id)
);

ALTER TABLE patient_intake_submission ENABLE ROW LEVEL SECURITY;
ALTER TABLE patient_intake_submission FORCE ROW LEVEL SECURITY;
CREATE POLICY patient_intake_submission_tenant_isolation ON patient_intake_submission
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);

CREATE INDEX patient_intake_submission_patient_idx
    ON patient_intake_submission (tenant_id, patient_id, created_at DESC);
