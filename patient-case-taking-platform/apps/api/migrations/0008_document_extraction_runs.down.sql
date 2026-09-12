ALTER TABLE document_registry
    DROP CONSTRAINT IF EXISTS document_registry_active_extraction_fk,
    DROP COLUMN IF EXISTS active_extraction_run_id;
DROP TABLE IF EXISTS document_extraction_candidate;
DROP TABLE IF EXISTS document_extraction_run;
