CREATE TABLE document_promotion_receipt (
    event_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    document_id UUID NOT NULL,
    promoted_fact_count INTEGER NOT NULL CHECK (promoted_fact_count >= 0),
    completed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id, document_id)
        REFERENCES document_registry (tenant_id, id),
    UNIQUE (tenant_id, event_id)
);

CREATE TABLE reviewed_document_fact (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    facility_id UUID NOT NULL,
    patient_id UUID NOT NULL,
    encounter_id UUID NOT NULL,
    document_id UUID NOT NULL,
    candidate_id UUID NOT NULL,
    candidate_version INTEGER NOT NULL CHECK (candidate_version > 1),
    review_decision_id UUID NOT NULL,
    entity_type VARCHAR(64) NOT NULL,
    normalized_value TEXT NOT NULL,
    unit VARCHAR(32),
    source_page_artifact_id UUID NOT NULL,
    source_ocr_artifact_id UUID,
    source_region_id UUID,
    source_page_number INTEGER NOT NULL CHECK (source_page_number > 0),
    document_statement BOOLEAN NOT NULL CHECK (document_statement),
    clinician_confirmed_current BOOLEAN NOT NULL CHECK (NOT clinician_confirmed_current),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    promoted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    withdrawn_at TIMESTAMPTZ,
    withdrawal_reason_code VARCHAR(64),
    FOREIGN KEY (tenant_id, document_id)
        REFERENCES document_registry (tenant_id, id),
    FOREIGN KEY (tenant_id, candidate_id)
        REFERENCES document_extraction_candidate (tenant_id, candidate_id),
    FOREIGN KEY (tenant_id, review_decision_id)
        REFERENCES document_review_decision (tenant_id, id),
    FOREIGN KEY (tenant_id, source_page_artifact_id)
        REFERENCES document_page_artifact (tenant_id, id),
    UNIQUE (tenant_id, candidate_id, candidate_version),
    UNIQUE (tenant_id, id)
);

CREATE TABLE document_fact_status_history (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    document_id UUID NOT NULL,
    fact_id UUID NOT NULL,
    actor_id UUID NOT NULL,
    actor_role VARCHAR(32) NOT NULL CHECK (actor_role IN ('doctor', 'nurse')),
    action VARCHAR(32) NOT NULL CHECK (action IN ('promoted', 'withdrawn', 'restored')),
    reason_code VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id, document_id)
        REFERENCES document_registry (tenant_id, id),
    FOREIGN KEY (tenant_id, fact_id)
        REFERENCES reviewed_document_fact (tenant_id, id),
    UNIQUE (tenant_id, id)
);

CREATE TABLE clinical_timeline_projection (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    patient_id UUID NOT NULL,
    encounter_id UUID NOT NULL,
    document_id UUID NOT NULL,
    fact_id UUID NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    display_value TEXT NOT NULL,
    unit VARCHAR(32),
    statement_status VARCHAR(32) NOT NULL CHECK (
        statement_status IN ('document_stated', 'clinician_confirmed_current')
    ),
    occurred_at TIMESTAMPTZ NOT NULL,
    rebuilt_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id, fact_id)
        REFERENCES reviewed_document_fact (tenant_id, id),
    UNIQUE (tenant_id, fact_id)
);

CREATE TABLE document_fhir_projection (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    document_id UUID NOT NULL,
    fact_id UUID NOT NULL,
    resource_type VARCHAR(64) NOT NULL,
    resource JSONB NOT NULL,
    rebuilt_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id, fact_id)
        REFERENCES reviewed_document_fact (tenant_id, id),
    UNIQUE (tenant_id, fact_id)
);

CREATE TABLE document_search_projection (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    patient_id UUID NOT NULL,
    document_id UUID NOT NULL,
    fact_id UUID NOT NULL,
    entity_type VARCHAR(64) NOT NULL,
    normalized_text TEXT NOT NULL,
    statement_status VARCHAR(32) NOT NULL,
    rebuilt_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id, fact_id)
        REFERENCES reviewed_document_fact (tenant_id, id),
    UNIQUE (tenant_id, fact_id)
);

ALTER TABLE document_promotion_receipt ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_promotion_receipt FORCE ROW LEVEL SECURITY;
CREATE POLICY document_promotion_receipt_tenant_isolation ON document_promotion_receipt
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);

ALTER TABLE reviewed_document_fact ENABLE ROW LEVEL SECURITY;
ALTER TABLE reviewed_document_fact FORCE ROW LEVEL SECURITY;
CREATE POLICY reviewed_document_fact_tenant_isolation ON reviewed_document_fact
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);

ALTER TABLE document_fact_status_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_fact_status_history FORCE ROW LEVEL SECURITY;
CREATE POLICY document_fact_status_history_tenant_isolation ON document_fact_status_history
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);

ALTER TABLE clinical_timeline_projection ENABLE ROW LEVEL SECURITY;
ALTER TABLE clinical_timeline_projection FORCE ROW LEVEL SECURITY;
CREATE POLICY clinical_timeline_projection_tenant_isolation ON clinical_timeline_projection
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);

ALTER TABLE document_fhir_projection ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_fhir_projection FORCE ROW LEVEL SECURITY;
CREATE POLICY document_fhir_projection_tenant_isolation ON document_fhir_projection
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);

ALTER TABLE document_search_projection ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_search_projection FORCE ROW LEVEL SECURITY;
CREATE POLICY document_search_projection_tenant_isolation ON document_search_projection
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);

CREATE INDEX reviewed_document_fact_patient_idx
    ON reviewed_document_fact (tenant_id, patient_id, promoted_at DESC)
    WHERE active;
CREATE INDEX clinical_timeline_patient_idx
    ON clinical_timeline_projection (tenant_id, patient_id, occurred_at DESC);
CREATE INDEX document_search_patient_idx
    ON document_search_projection (tenant_id, patient_id, entity_type);
