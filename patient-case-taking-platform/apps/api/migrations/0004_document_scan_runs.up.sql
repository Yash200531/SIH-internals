CREATE TABLE document_scan_run (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    document_id UUID NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt > 0),
    status VARCHAR(32) NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    outcome VARCHAR(32) CHECK (outcome IN ('clean', 'infected')),
    engine VARCHAR(64),
    engine_version VARCHAR(128),
    signature_version VARCHAR(128),
    threat_name VARCHAR(255),
    error_class VARCHAR(128),
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,
    FOREIGN KEY (tenant_id, document_id)
        REFERENCES document_registry (tenant_id, id),
    UNIQUE (tenant_id, document_id, attempt),
    UNIQUE (tenant_id, id)
);

ALTER TABLE document_scan_run ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_scan_run FORCE ROW LEVEL SECURITY;
CREATE POLICY document_scan_run_tenant_isolation ON document_scan_run
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);

ALTER TABLE document_registry
    ADD COLUMN active_processing_run_id UUID,
    ADD COLUMN processing_object_key TEXT,
    ADD CONSTRAINT document_registry_active_scan_fk
        FOREIGN KEY (tenant_id, active_processing_run_id)
        REFERENCES document_scan_run (tenant_id, id);

CREATE INDEX document_scan_run_status_idx
    ON document_scan_run (tenant_id, status, started_at);
