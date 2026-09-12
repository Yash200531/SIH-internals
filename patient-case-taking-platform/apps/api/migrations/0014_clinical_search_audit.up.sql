CREATE TABLE clinical_search_audit (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    patient_id UUID NOT NULL,
    actor_id UUID NOT NULL,
    actor_role VARCHAR(32) NOT NULL CHECK (actor_role IN ('patient', 'doctor', 'nurse')),
    action VARCHAR(32) NOT NULL CHECK (
        action IN ('search', 'timeline', 'fhir_search', 'export')
    ),
    purpose VARCHAR(32) NOT NULL CHECK (purpose = 'treatment'),
    authorized_facility_ids UUID[] NOT NULL CHECK (
        cardinality(authorized_facility_ids) BETWEEN 1 AND 100
    ),
    query_sha256 CHAR(64) NOT NULL CHECK (query_sha256 ~ '^[0-9a-f]{64}$'),
    filter_metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    result_count INTEGER CHECK (result_count IS NULL OR result_count >= 0),
    latency_ms INTEGER NOT NULL CHECK (latency_ms >= 0),
    outcome VARCHAR(32) NOT NULL CHECK (outcome IN ('success', 'unavailable', 'error')),
    correlation_id UUID NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE clinical_search_audit ENABLE ROW LEVEL SECURITY;
ALTER TABLE clinical_search_audit FORCE ROW LEVEL SECURITY;
CREATE POLICY clinical_search_audit_tenant_isolation ON clinical_search_audit
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);

CREATE INDEX clinical_search_audit_tenant_time_idx
    ON clinical_search_audit (tenant_id, occurred_at DESC);
CREATE INDEX clinical_search_audit_patient_time_idx
    ON clinical_search_audit (tenant_id, patient_id, occurred_at DESC);
