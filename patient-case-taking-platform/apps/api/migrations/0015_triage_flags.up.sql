-- Phase 6 alert persistence. Rule evidence is metadata only; rationale is protected history.
CREATE TABLE triage_flag (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    facility_id UUID NOT NULL,
    encounter_id UUID NOT NULL,
    input_version INTEGER NOT NULL CHECK (input_version > 0),
    rule_id VARCHAR(128) NOT NULL,
    rule_version VARCHAR(64) NOT NULL,
    ruleset_version VARCHAR(128) NOT NULL,
    evidence_fingerprint CHAR(64) NOT NULL CHECK (evidence_fingerprint ~ '^[0-9a-f]{64}$'),
    rule_metadata JSONB NOT NULL,
    lifecycle JSONB NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (tenant_id, id),
    UNIQUE (tenant_id, facility_id, encounter_id, input_version, rule_id, rule_version, ruleset_version, evidence_fingerprint),
    CHECK ((lifecycle->>'id')::UUID = id),
    CHECK ((lifecycle->>'tenant_id')::UUID = tenant_id),
    CHECK ((lifecycle->>'facility_id')::UUID = facility_id),
    CHECK ((lifecycle->>'encounter_id')::UUID = encounter_id),
    CHECK ((lifecycle->>'version')::INTEGER = version),
    CHECK (lifecycle->>'state' IN ('open','acknowledged','escalated','resolved','overridden'))
);
CREATE INDEX triage_flag_queue_idx ON triage_flag (tenant_id, facility_id, created_at, id);
CREATE TABLE triage_flag_history (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    flag_id UUID NOT NULL,
    version INTEGER NOT NULL,
    actor_id UUID NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    request_hash CHAR(64) NOT NULL,
    action VARCHAR(32) NOT NULL,
    protected_detail JSONB NOT NULL,
    result JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (tenant_id, flag_id, version),
    UNIQUE (tenant_id, flag_id, idempotency_key),
    FOREIGN KEY (tenant_id, flag_id) REFERENCES triage_flag (tenant_id, id)
);
CREATE TABLE triage_outbox (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    flag_id UUID NOT NULL,
    flag_version INTEGER NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    published_at TIMESTAMPTZ,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (tenant_id, flag_id, flag_version),
    FOREIGN KEY (tenant_id, flag_id) REFERENCES triage_flag (tenant_id, id)
);
CREATE INDEX triage_outbox_pending_idx ON triage_outbox (next_attempt_at, id) WHERE published_at IS NULL;
CREATE FUNCTION reject_triage_history_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Triage history is append-only';
END;
$$;
CREATE TRIGGER triage_history_immutable BEFORE UPDATE OR DELETE ON triage_flag_history
FOR EACH ROW EXECUTE FUNCTION reject_triage_history_mutation();
ALTER TABLE triage_flag ENABLE ROW LEVEL SECURITY;
ALTER TABLE triage_flag FORCE ROW LEVEL SECURITY;
ALTER TABLE triage_flag_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE triage_flag_history FORCE ROW LEVEL SECURITY;
ALTER TABLE triage_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE triage_outbox FORCE ROW LEVEL SECURITY;
CREATE POLICY triage_flag_tenant ON triage_flag
USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);
CREATE POLICY triage_history_tenant ON triage_flag_history
USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);
CREATE POLICY triage_outbox_tenant ON triage_outbox
USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);
