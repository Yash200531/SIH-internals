ALTER TABLE document_registry
    DROP CONSTRAINT IF EXISTS document_registry_active_normalization_fk,
    DROP COLUMN IF EXISTS active_normalization_run_id;
DROP TABLE IF EXISTS document_page_artifact;
DROP TABLE IF EXISTS document_normalization_run;
