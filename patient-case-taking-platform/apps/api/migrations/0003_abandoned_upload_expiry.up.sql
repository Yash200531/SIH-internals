ALTER TABLE document_registry
    ADD COLUMN upload_expires_at TIMESTAMPTZ NOT NULL
    DEFAULT (CURRENT_TIMESTAMP + INTERVAL '15 minutes');

CREATE INDEX document_registry_abandoned_upload_idx
    ON document_registry (upload_expires_at)
    WHERE state = 'initiated';
