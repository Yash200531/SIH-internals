DROP INDEX IF EXISTS document_registry_abandoned_upload_idx;
ALTER TABLE document_registry DROP COLUMN IF EXISTS upload_expires_at;
