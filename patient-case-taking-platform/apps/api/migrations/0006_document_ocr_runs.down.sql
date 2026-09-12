ALTER TABLE document_registry
    DROP CONSTRAINT IF EXISTS document_registry_active_ocr_fk,
    DROP COLUMN IF EXISTS active_ocr_run_id;
DROP TABLE IF EXISTS document_ocr_page_ref;
DROP TABLE IF EXISTS document_ocr_run;
ALTER TABLE document_page_artifact
    DROP CONSTRAINT IF EXISTS document_page_artifact_tenant_id_unique;
