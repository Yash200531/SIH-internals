ALTER TABLE document_page_artifact
    ADD CONSTRAINT document_page_artifact_tenant_id_unique UNIQUE (tenant_id, id);

CREATE TABLE document_ocr_run (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    document_id UUID NOT NULL,
    normalization_run_id UUID NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt > 0),
    provider VARCHAR(64) NOT NULL,
    model_version VARCHAR(128) NOT NULL,
    language_pack_version VARCHAR(128) NOT NULL,
    schema_version VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL
        CHECK (status IN ('running', 'completed', 'failed', 'dead_letter')),
    error_class VARCHAR(128),
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    lease_expires_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    FOREIGN KEY (tenant_id, document_id)
        REFERENCES document_registry (tenant_id, id),
    FOREIGN KEY (tenant_id, normalization_run_id)
        REFERENCES document_normalization_run (tenant_id, id),
    UNIQUE (tenant_id, document_id, attempt),
    UNIQUE (tenant_id, id)
);

CREATE TABLE document_ocr_page_ref (
    artifact_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    document_id UUID NOT NULL,
    ocr_run_id UUID NOT NULL,
    page_artifact_id UUID NOT NULL,
    page_number INTEGER NOT NULL CHECK (page_number > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id, document_id)
        REFERENCES document_registry (tenant_id, id),
    FOREIGN KEY (tenant_id, ocr_run_id)
        REFERENCES document_ocr_run (tenant_id, id),
    FOREIGN KEY (tenant_id, page_artifact_id)
        REFERENCES document_page_artifact (tenant_id, id),
    UNIQUE (tenant_id, ocr_run_id, page_artifact_id),
    UNIQUE (tenant_id, artifact_id)
);

ALTER TABLE document_ocr_run ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_ocr_run FORCE ROW LEVEL SECURITY;
CREATE POLICY document_ocr_run_tenant_isolation ON document_ocr_run
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);

ALTER TABLE document_ocr_page_ref ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_ocr_page_ref FORCE ROW LEVEL SECURITY;
CREATE POLICY document_ocr_page_ref_tenant_isolation ON document_ocr_page_ref
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);

ALTER TABLE document_registry
    ADD COLUMN active_ocr_run_id UUID,
    ADD CONSTRAINT document_registry_active_ocr_fk
        FOREIGN KEY (tenant_id, active_ocr_run_id)
        REFERENCES document_ocr_run (tenant_id, id);

CREATE INDEX document_ocr_run_queue_idx
    ON document_ocr_run (status, lease_expires_at);
CREATE INDEX document_ocr_page_ref_document_idx
    ON document_ocr_page_ref (tenant_id, document_id, page_number);
