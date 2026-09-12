CREATE TABLE document_registry (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    facility_id UUID NOT NULL,
    patient_id UUID NOT NULL,
    encounter_id UUID NOT NULL,
    uploader_actor_id UUID NOT NULL,
    purpose VARCHAR(64) NOT NULL,
    consent_reference VARCHAR(256) NOT NULL,
    original_filename VARCHAR(255) NOT NULL,
    declared_mime VARCHAR(127) NOT NULL,
    declared_size_bytes BIGINT NOT NULL CHECK (declared_size_bytes > 0),
    idempotency_key VARCHAR(128) NOT NULL,
    state VARCHAR(32) NOT NULL DEFAULT 'initiated' CHECK (
        state IN (
            'initiated', 'uploaded', 'quarantined', 'scanning',
            'scan_rejected', 'scan_passed', 'processing',
            'processing_failed', 'review_required', 'reviewed',
            'cancelled', 'retention_hold', 'deletion_pending'
        )
    ),
    object_key TEXT,
    source_checksum_sha256 CHAR(64) CHECK (
        source_checksum_sha256 IS NULL
        OR source_checksum_sha256 ~ '^[0-9a-f]{64}$'
    ),
    detected_mime VARCHAR(127),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (tenant_id, id),
    UNIQUE (tenant_id, idempotency_key),
    UNIQUE (tenant_id, object_key)
);

ALTER TABLE document_registry ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_registry FORCE ROW LEVEL SECURITY;
CREATE POLICY document_registry_tenant_isolation ON document_registry
    USING (
        tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
    );

CREATE TABLE document_outbox (
    event_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    aggregate_id UUID NOT NULL,
    aggregate_type VARCHAR(64) NOT NULL DEFAULT 'document',
    event_type VARCHAR(128) NOT NULL,
    event_version INTEGER NOT NULL CHECK (event_version > 0),
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    producer VARCHAR(128) NOT NULL,
    correlation_id UUID NOT NULL,
    causation_id UUID,
    data_classification VARCHAR(32) NOT NULL DEFAULT 'restricted',
    idempotency_key VARCHAR(192) NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0),
    artifact_refs JSONB NOT NULL DEFAULT '[]'::JSONB,
    payload JSONB NOT NULL DEFAULT '{}'::JSONB,
    published_at TIMESTAMPTZ,
    last_error_class VARCHAR(128),
    FOREIGN KEY (tenant_id, aggregate_id)
        REFERENCES document_registry (tenant_id, id),
    UNIQUE (tenant_id, idempotency_key)
);

ALTER TABLE document_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_outbox FORCE ROW LEVEL SECURITY;
CREATE POLICY document_outbox_tenant_isolation ON document_outbox
    USING (
        tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
    );

CREATE INDEX document_registry_review_queue_idx
    ON document_registry (tenant_id, facility_id, state, updated_at);
CREATE INDEX document_outbox_unpublished_idx
    ON document_outbox (occurred_at)
    WHERE published_at IS NULL;
