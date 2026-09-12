DROP INDEX IF EXISTS document_review_queue_idx;
DROP INDEX IF EXISTS document_review_decision_document_idx;
DROP TRIGGER IF EXISTS document_review_decision_append_only ON document_review_decision;
DROP FUNCTION IF EXISTS prevent_document_review_decision_mutation();
DROP TABLE IF EXISTS document_review_decision;

ALTER TABLE document_extraction_candidate
    ALTER COLUMN source_region_id SET NOT NULL,
    ALTER COLUMN source_ocr_artifact_id SET NOT NULL,
    ALTER COLUMN draft_id SET NOT NULL,
    ALTER COLUMN extraction_run_id SET NOT NULL,
    DROP COLUMN IF EXISTS created_by_actor_id,
    DROP COLUMN IF EXISTS candidate_origin,
    DROP COLUMN IF EXISTS source_polygon,
    DROP COLUMN IF EXISTS source_bbox,
    DROP COLUMN IF EXISTS source_page_height,
    DROP COLUMN IF EXISTS source_page_width;

ALTER TABLE document_extraction_candidate
    DROP CONSTRAINT IF EXISTS document_extraction_candidate_review_state_check;
ALTER TABLE document_extraction_candidate
    ADD CONSTRAINT document_extraction_candidate_review_state_check
        CHECK (review_state IN ('unreviewed', 'accepted', 'corrected', 'rejected'));
