CREATE TABLE confirmed_encounter_summary_context (
    tenant_id UUID NOT NULL,
    facility_id UUID NOT NULL,
    patient_id UUID NOT NULL,
    encounter_id UUID NOT NULL,
    language CHAR(2) NOT NULL CHECK (language IN ('hi', 'en')),
    chief_complaint VARCHAR(500) NOT NULL,
    confirmed_answers JSONB NOT NULL DEFAULT '{}'::JSONB,
    deterministic_red_flags JSONB NOT NULL DEFAULT '[]'::JSONB,
    confirmed_by_actor_id UUID NOT NULL,
    confirmed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    PRIMARY KEY (tenant_id, encounter_id)
);

ALTER TABLE confirmed_encounter_summary_context ENABLE ROW LEVEL SECURITY;
ALTER TABLE confirmed_encounter_summary_context FORCE ROW LEVEL SECURITY;
CREATE POLICY confirmed_encounter_summary_context_tenant_isolation
    ON confirmed_encounter_summary_context
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);

CREATE TABLE clinical_summary_workflow (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    facility_id UUID NOT NULL,
    patient_id UUID NOT NULL,
    encounter_id UUID NOT NULL,
    lineage_id UUID NOT NULL,
    generation INTEGER NOT NULL CHECK (generation > 0),
    parent_summary_id UUID,
    status VARCHAR(32) NOT NULL CHECK (
        status IN ('draft', 'in_review', 'rejected', 'signed', 'superseded')
    ),
    content JSONB NOT NULL,
    evidence JSONB NOT NULL DEFAULT '[]'::JSONB,
    confidence JSONB NOT NULL,
    provider VARCHAR(32) NOT NULL CHECK (provider IN ('mock', 'template-fallback')),
    schema_version VARCHAR(64) NOT NULL CHECK (
        schema_version = 'phase8.summary-workflow.v1'
    ),
    degraded BOOLEAN NOT NULL DEFAULT FALSE,
    lock_version INTEGER NOT NULL DEFAULT 1 CHECK (lock_version > 0),
    created_by_actor_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    signed_by_actor_id UUID,
    signed_at TIMESTAMPTZ,
    signature_sha256 CHAR(64) CHECK (
        signature_sha256 IS NULL OR signature_sha256 ~ '^[0-9a-f]{64}$'
    ),
    rejection_reason VARCHAR(500),
    idempotency_key VARCHAR(128) NOT NULL,
    request_hash_sha256 CHAR(64) NOT NULL CHECK (
        request_hash_sha256 ~ '^[0-9a-f]{64}$'
    ),
    UNIQUE (tenant_id, id),
    UNIQUE (tenant_id, idempotency_key),
    UNIQUE (tenant_id, lineage_id, generation),
    FOREIGN KEY (tenant_id, parent_summary_id)
        REFERENCES clinical_summary_workflow (tenant_id, id),
    CHECK (
        (status = 'signed' AND signed_by_actor_id IS NOT NULL
         AND signed_at IS NOT NULL AND signature_sha256 IS NOT NULL)
        OR
        (status <> 'signed' AND signed_by_actor_id IS NULL
         AND signed_at IS NULL AND signature_sha256 IS NULL)
    )
);

CREATE TABLE clinical_summary_action (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    summary_id UUID NOT NULL,
    actor_id UUID NOT NULL,
    actor_role VARCHAR(32) NOT NULL CHECK (actor_role IN ('doctor', 'nurse', 'system')),
    action VARCHAR(32) NOT NULL CHECK (
        action IN ('generated', 'edited', 'submitted', 'rejected', 'regenerated', 'signed')
    ),
    from_status VARCHAR(32),
    to_status VARCHAR(32) NOT NULL,
    resulting_lock_version INTEGER NOT NULL CHECK (resulting_lock_version > 0),
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id, summary_id)
        REFERENCES clinical_summary_workflow (tenant_id, id),
    UNIQUE (tenant_id, id)
);

CREATE TABLE clinical_summary_outbox (
    event_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    summary_id UUID NOT NULL,
    event_type VARCHAR(128) NOT NULL,
    event_version INTEGER NOT NULL DEFAULT 1 CHECK (event_version > 0),
    idempotency_key VARCHAR(192) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::JSONB,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    published_at TIMESTAMPTZ,
    attempt INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0),
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    publish_lease_expires_at TIMESTAMPTZ,
    dead_lettered_at TIMESTAMPTZ,
    last_error_class VARCHAR(128),
    FOREIGN KEY (tenant_id, summary_id)
        REFERENCES clinical_summary_workflow (tenant_id, id),
    UNIQUE (tenant_id, idempotency_key)
);

ALTER TABLE clinical_summary_workflow ENABLE ROW LEVEL SECURITY;
ALTER TABLE clinical_summary_workflow FORCE ROW LEVEL SECURITY;
CREATE POLICY clinical_summary_workflow_tenant_isolation ON clinical_summary_workflow
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);

ALTER TABLE clinical_summary_action ENABLE ROW LEVEL SECURITY;
ALTER TABLE clinical_summary_action FORCE ROW LEVEL SECURITY;
CREATE POLICY clinical_summary_action_tenant_isolation ON clinical_summary_action
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);

ALTER TABLE clinical_summary_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE clinical_summary_outbox FORCE ROW LEVEL SECURITY;
CREATE POLICY clinical_summary_outbox_tenant_isolation ON clinical_summary_outbox
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);

CREATE OR REPLACE FUNCTION prevent_clinical_summary_action_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'clinical summary actions are append-only';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER clinical_summary_action_append_only
BEFORE UPDATE OR DELETE ON clinical_summary_action
FOR EACH ROW EXECUTE FUNCTION prevent_clinical_summary_action_mutation();

CREATE OR REPLACE FUNCTION prevent_signed_clinical_summary_mutation()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.status = 'signed' THEN
        RAISE EXCEPTION 'signed clinical summaries are immutable';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER clinical_summary_signed_immutable
BEFORE UPDATE OR DELETE ON clinical_summary_workflow
FOR EACH ROW EXECUTE FUNCTION prevent_signed_clinical_summary_mutation();

CREATE INDEX clinical_summary_encounter_idx
    ON clinical_summary_workflow (tenant_id, encounter_id, generation DESC);
CREATE INDEX clinical_summary_review_queue_idx
    ON clinical_summary_workflow (tenant_id, facility_id, status, updated_at DESC);
CREATE INDEX clinical_summary_outbox_pending_idx
    ON clinical_summary_outbox (next_attempt_at, occurred_at)
    WHERE published_at IS NULL AND dead_lettered_at IS NULL;
