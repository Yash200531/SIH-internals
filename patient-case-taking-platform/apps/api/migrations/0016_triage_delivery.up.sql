ALTER TABLE triage_outbox ADD COLUMN lease_id UUID;
ALTER TABLE triage_outbox ADD COLUMN dead_lettered_at TIMESTAMPTZ;
ALTER TABLE triage_outbox ADD COLUMN last_error_class VARCHAR(128);
