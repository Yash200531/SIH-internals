CREATE TABLE auth_identity_binding (
    issuer VARCHAR(255) NOT NULL,
    audience VARCHAR(128) NOT NULL,
    subject VARCHAR(128) NOT NULL,
    internal_id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    role VARCHAR(32) NOT NULL,
    facility_ids UUID[] NOT NULL CHECK (cardinality(facility_ids) BETWEEN 1 AND 50),
    active BOOLEAN NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    PRIMARY KEY (issuer,audience,subject)
);
CREATE TABLE auth_identity_history (
    id UUID PRIMARY KEY,
    issuer VARCHAR(255) NOT NULL,
    audience VARCHAR(128) NOT NULL,
    subject VARCHAR(128) NOT NULL,
    version INTEGER NOT NULL,
    operator_id UUID NOT NULL,
    reason_code VARCHAR(64) NOT NULL,
    binding JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (issuer,audience,subject,version),
    FOREIGN KEY (issuer,audience,subject) REFERENCES auth_identity_binding
);
CREATE TABLE auth_revoked_session (
    issuer VARCHAR(255) NOT NULL,
    audience VARCHAR(128) NOT NULL,
    subject VARCHAR(128) NOT NULL,
    session_id VARCHAR(128) NOT NULL,
    revoked_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (issuer,audience,subject,session_id),
    FOREIGN KEY (issuer,audience,subject) REFERENCES auth_identity_binding
);
CREATE FUNCTION reject_auth_history_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Identity history is append-only';
END;
$$;
CREATE TRIGGER auth_identity_history_immutable BEFORE UPDATE OR DELETE ON auth_identity_history
FOR EACH ROW EXECUTE FUNCTION reject_auth_history_mutation();
-- Identity lookup precedes tenant authorization. Scope it to the cryptographically
-- verified issuer/audience/subject, never a caller-provided tenant claim.
DO $$
DECLARE owned_table TEXT;
BEGIN
    FOREACH owned_table IN ARRAY ARRAY['auth_identity_binding','auth_identity_history','auth_revoked_session'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', owned_table);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', owned_table);
        EXECUTE format('CREATE POLICY identity_subject_scope ON %I USING (
            issuer=current_setting(''app.auth_issuer'',true)
            AND audience=current_setting(''app.auth_audience'',true)
            AND subject=current_setting(''app.auth_subject'',true)
        ) WITH CHECK (
            issuer=current_setting(''app.auth_issuer'',true)
            AND audience=current_setting(''app.auth_audience'',true)
            AND subject=current_setting(''app.auth_subject'',true)
        )', owned_table);
    END LOOP;
END;
$$;
