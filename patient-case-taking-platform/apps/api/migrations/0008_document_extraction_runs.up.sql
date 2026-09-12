CREATE TABLE document_extraction_run (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    document_id UUID NOT NULL,
    ocr_run_id UUID NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt > 0),
    parser_version VARCHAR(64) NOT NULL,
    schema_version VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL
        CHECK (status IN ('running', 'completed', 'failed', 'dead_letter')),
    error_class VARCHAR(128),
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    lease_expires_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    FOREIGN KEY (tenant_id, document_id)
        REFERENCES document_registry (tenant_id, id),
    FOREIGN KEY (tenant_id, ocr_run_id)
        REFERENCES document_ocr_run (tenant_id, id),
    UNIQUE (tenant_id, document_id, attempt),
    UNIQUE (tenant_id, id)
);

CREATE TABLE document_extraction_candidate (
    candidate_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    document_id UUID NOT NULL,
    extraction_run_id UUID NOT NULL,
    draft_id UUID NOT NULL,
    entity_type VARCHAR(64) NOT NULL,
    normalized_value TEXT,
    unit VARCHAR(32),
    source_page_artifact_id UUID NOT NULL,
    source_ocr_artifact_id UUID NOT NULL,
    source_region_id UUID NOT NULL,
    source_page_number INTEGER NOT NULL CHECK (source_page_number > 0),
    parser_version VARCHAR(64) NOT NULL,
    parser_signal VARCHAR(128) NOT NULL,
    negated BOOLEAN NOT NULL,
    temporality VARCHAR(32) NOT NULL,
    subject VARCHAR(32) NOT NULL,
    uncertainty VARCHAR(128),
    document_statement BOOLEAN NOT NULL CHECK (document_statement),
    clinician_confirmed_current BOOLEAN NOT NULL CHECK (NOT clinician_confirmed_current),
    review_state VARCHAR(32) NOT NULL DEFAULT 'unreviewed'
        CHECK (review_state IN ('unreviewed', 'accepted', 'corrected', 'rejected')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id, document_id)
        REFERENCES document_registry (tenant_id, id),
    FOREIGN KEY (tenant_id, extraction_run_id)
        REFERENCES document_extraction_run (tenant_id, id),
    FOREIGN KEY (tenant_id, source_page_artifact_id)
        REFERENCES document_page_artifact (tenant_id, id),
    FOREIGN KEY (tenant_id, source_ocr_artifact_id)
        REFERENCES document_ocr_page_ref (tenant_id, artifact_id),
    UNIQUE (tenant_id, extraction_run_id, candidate_id),
    UNIQUE (tenant_id, candidate_id)
);

ALTER TABLE document_extraction_run ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_extraction_run FORCE ROW LEVEL SECURITY;
CREATE POLICY document_extraction_run_tenant_isolation ON document_extraction_run
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);

ALTER TABLE document_extraction_candidate ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_extraction_candidate FORCE ROW LEVEL SECURITY;
CREATE POLICY document_extraction_candidate_tenant_isolation ON document_extraction_candidate
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);

ALTER TABLE document_registry
    ADD COLUMN active_extraction_run_id UUID,
    ADD CONSTRAINT document_registry_active_extraction_fk
        FOREIGN KEY (tenant_id, active_extraction_run_id)
        REFERENCES document_extraction_run (tenant_id, id);

CREATE INDEX document_extraction_run_queue_idx
    ON document_extraction_run (status, lease_expires_at);
CREATE INDEX document_extraction_candidate_review_idx
    ON document_extraction_candidate (tenant_id, document_id, review_state, entity_type);
