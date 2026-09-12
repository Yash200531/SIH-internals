CREATE TABLE patient_intake_session (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    patient_id UUID NOT NULL,
    facility_id UUID NOT NULL,
    encounter_id UUID NOT NULL UNIQUE,
    owner_session_hash CHAR(64) NOT NULL,
    idempotency_key UUID NOT NULL,
    language VARCHAR(2) NOT NULL CHECK (language IN ('en','hi')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP + INTERVAL '5 minutes',
    hard_expires_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP + INTERVAL '30 minutes',
    ended_at TIMESTAMPTZ,
    UNIQUE (tenant_id,patient_id,owner_session_hash,idempotency_key)
);
CREATE INDEX patient_intake_session_owner ON patient_intake_session(tenant_id,patient_id,owner_session_hash);
CREATE TABLE patient_intake_session_history (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    patient_id UUID NOT NULL,
    session_id UUID NOT NULL REFERENCES patient_intake_session(id),
    action VARCHAR(16) NOT NULL CHECK(action IN ('created','ended')),
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TRIGGER patient_intake_history_immutable BEFORE UPDATE OR DELETE ON patient_intake_session_history
FOR EACH ROW EXECUTE FUNCTION reject_auth_history_mutation();
ALTER TABLE patient_intake_session_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE patient_intake_session_history FORCE ROW LEVEL SECURITY;
CREATE POLICY patient_session_history_scope ON patient_intake_session_history USING (
    tenant_id::TEXT=current_setting('app.tenant_id',true)
    AND patient_id::TEXT=current_setting('app.patient_id',true)
) WITH CHECK (
    tenant_id::TEXT=current_setting('app.tenant_id',true)
    AND patient_id::TEXT=current_setting('app.patient_id',true)
);
ALTER TABLE patient_intake_session ENABLE ROW LEVEL SECURITY;
ALTER TABLE patient_intake_session FORCE ROW LEVEL SECURITY;
CREATE POLICY patient_session_scope ON patient_intake_session USING (
    tenant_id::TEXT=current_setting('app.tenant_id',true)
    AND patient_id::TEXT=current_setting('app.patient_id',true)
) WITH CHECK (
    tenant_id::TEXT=current_setting('app.tenant_id',true)
    AND patient_id::TEXT=current_setting('app.patient_id',true)
);
