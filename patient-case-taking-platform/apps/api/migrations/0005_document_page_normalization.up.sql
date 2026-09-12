CREATE TABLE document_normalization_run (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    document_id UUID NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt > 0),
    preprocessing_version VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    error_class VARCHAR(128),
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,
    FOREIGN KEY (tenant_id, document_id)
        REFERENCES document_registry (tenant_id, id),
    UNIQUE (tenant_id, document_id, attempt),
    UNIQUE (tenant_id, id)
);

CREATE TABLE document_page_artifact (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    document_id UUID NOT NULL,
    normalization_run_id UUID NOT NULL,
    page_number INTEGER NOT NULL CHECK (page_number > 0),
    object_key TEXT NOT NULL,
    checksum_sha256 CHAR(64) NOT NULL CHECK (checksum_sha256 ~ '^[0-9a-f]{64}$'),
    mime VARCHAR(127) NOT NULL,
    width INTEGER NOT NULL CHECK (width > 0),
    height INTEGER NOT NULL CHECK (height > 0),
    preprocessing_version VARCHAR(64) NOT NULL,
    operations JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id, document_id)
        REFERENCES document_registry (tenant_id, id),
    FOREIGN KEY (tenant_id, normalization_run_id)
        REFERENCES document_normalization_run (tenant_id, id),
    UNIQUE (tenant_id, normalization_run_id, page_number),
    UNIQUE (tenant_id, object_key)
);

ALTER TABLE document_normalization_run ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_normalization_run FORCE ROW LEVEL SECURITY;
CREATE POLICY document_normalization_run_tenant_isolation ON document_normalization_run
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);

ALTER TABLE document_page_artifact ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_page_artifact FORCE ROW LEVEL SECURITY;
CREATE POLICY document_page_artifact_tenant_isolation ON document_page_artifact
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);

ALTER TABLE document_registry
    ADD COLUMN active_normalization_run_id UUID,
    ADD CONSTRAINT document_registry_active_normalization_fk
        FOREIGN KEY (tenant_id, active_normalization_run_id)
        REFERENCES document_normalization_run (tenant_id, id);

CREATE INDEX document_page_artifact_document_idx
    ON document_page_artifact (tenant_id, document_id, page_number);
