ALTER TABLE document_extraction_candidate
    DROP CONSTRAINT document_extraction_candidate_review_state_check;

ALTER TABLE document_extraction_candidate
    ADD CONSTRAINT document_extraction_candidate_review_state_check
        CHECK (review_state IN (
            'unreviewed', 'accepted', 'corrected', 'rejected',
            'unreadable', 'rescan_requested', 'deferred'
        ));

ALTER TABLE document_extraction_candidate
    ADD COLUMN source_page_width INTEGER CHECK (source_page_width > 0),
    ADD COLUMN source_page_height INTEGER CHECK (source_page_height > 0),
    ADD COLUMN source_bbox JSONB,
    ADD COLUMN source_polygon JSONB,
    ADD COLUMN candidate_origin VARCHAR(32) NOT NULL DEFAULT 'extracted'
        CHECK (candidate_origin IN ('extracted', 'manual')),
    ADD COLUMN created_by_actor_id UUID;

ALTER TABLE document_extraction_candidate
    ALTER COLUMN extraction_run_id DROP NOT NULL,
    ALTER COLUMN draft_id DROP NOT NULL,
    ALTER COLUMN source_ocr_artifact_id DROP NOT NULL,
    ALTER COLUMN source_region_id DROP NOT NULL;

CREATE TABLE document_review_decision (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    facility_id UUID NOT NULL,
    document_id UUID NOT NULL,
    candidate_id UUID NOT NULL,
    actor_id UUID NOT NULL,
    actor_role VARCHAR(32) NOT NULL CHECK (actor_role IN ('doctor', 'nurse')),
    purpose VARCHAR(64) NOT NULL CHECK (purpose = 'treatment'),
    action VARCHAR(32) NOT NULL CHECK (action IN (
        'accept', 'correct', 'reject', 'unreadable', 'request_rescan', 'defer',
        'manual_entry'
    )),
    previous_state VARCHAR(32) NOT NULL,
    resulting_state VARCHAR(32) NOT NULL,
    expected_candidate_version INTEGER NOT NULL CHECK (expected_candidate_version > 0),
    resulting_candidate_version INTEGER NOT NULL CHECK (resulting_candidate_version > 1),
    corrected_value TEXT,
    corrected_unit VARCHAR(32),
    reason_code VARCHAR(64),
    source_verified BOOLEAN NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    request_hash_sha256 CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id, document_id)
        REFERENCES document_registry (tenant_id, id),
    FOREIGN KEY (tenant_id, candidate_id)
        REFERENCES document_extraction_candidate (tenant_id, candidate_id),
    UNIQUE (tenant_id, idempotency_key),
    UNIQUE (tenant_id, id)
);

ALTER TABLE document_review_decision ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_review_decision FORCE ROW LEVEL SECURITY;
CREATE POLICY document_review_decision_tenant_isolation ON document_review_decision
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID);

CREATE OR REPLACE FUNCTION prevent_document_review_decision_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'document review decisions are append-only';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER document_review_decision_append_only
BEFORE UPDATE OR DELETE ON document_review_decision
FOR EACH ROW EXECUTE FUNCTION prevent_document_review_decision_mutation();

CREATE INDEX document_review_decision_document_idx
    ON document_review_decision (tenant_id, document_id, created_at);
CREATE INDEX document_review_queue_idx
    ON document_registry (tenant_id, facility_id, updated_at)
    WHERE state = 'review_required';
