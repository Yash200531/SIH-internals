ALTER TABLE document_outbox
    ADD COLUMN publish_lease_expires_at TIMESTAMPTZ,
    ADD COLUMN next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ADD COLUMN dead_lettered_at TIMESTAMPTZ;

CREATE INDEX document_outbox_delivery_idx
    ON document_outbox (next_attempt_at, occurred_at)
    WHERE published_at IS NULL AND dead_lettered_at IS NULL;
