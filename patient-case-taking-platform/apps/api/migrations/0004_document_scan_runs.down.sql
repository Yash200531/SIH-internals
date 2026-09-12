ALTER TABLE document_registry
    DROP CONSTRAINT IF EXISTS document_registry_active_scan_fk,
    DROP COLUMN IF EXISTS processing_object_key,
    DROP COLUMN IF EXISTS active_processing_run_id;
DROP TABLE IF EXISTS document_scan_run;
