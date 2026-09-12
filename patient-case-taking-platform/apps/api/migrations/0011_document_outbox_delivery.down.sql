DROP INDEX IF EXISTS document_outbox_delivery_idx;
ALTER TABLE document_outbox
    DROP COLUMN IF EXISTS dead_lettered_at,
    DROP COLUMN IF EXISTS next_attempt_at,
    DROP COLUMN IF EXISTS publish_lease_expires_at;
