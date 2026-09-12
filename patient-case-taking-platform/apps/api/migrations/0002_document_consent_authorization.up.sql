CREATE TABLE consent_artifact (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    patient_id UUID NOT NULL,
    encounter_id UUID NOT NULL,
    purpose VARCHAR(64) NOT NULL,
    scope JSONB NOT NULL DEFAULT '{}'::JSONB,
    status VARCHAR(32) NOT NULL CHECK (status IN ('granted', 'expired', 'revoked', 'denied')),
    granted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (expires_at IS NULL OR expires_at > granted_at),
    UNIQUE (tenant_id, id)
);

ALTER TABLE consent_artifact ENABLE ROW LEVEL SECURITY;
ALTER TABLE consent_artifact FORCE ROW LEVEL SECURITY;
CREATE POLICY consent_artifact_tenant_isolation ON consent_artifact
    USING (
        tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
    );

CREATE INDEX consent_artifact_authorization_idx
    ON consent_artifact (tenant_id, patient_id, encounter_id, purpose, status);
