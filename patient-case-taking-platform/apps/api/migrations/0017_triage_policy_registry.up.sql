CREATE TABLE triage_policy_artifact (
    tenant_id UUID NOT NULL,
    facility_id UUID NOT NULL,
    fingerprint CHAR(64) NOT NULL,
    policy_id VARCHAR(64) NOT NULL,
    policy_version VARCHAR(32) NOT NULL,
    document JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id,facility_id,fingerprint),
    UNIQUE (tenant_id,facility_id,policy_id,policy_version)
);
CREATE TABLE triage_active_policy (
    tenant_id UUID NOT NULL,
    facility_id UUID NOT NULL,
    fingerprint CHAR(64),
    revision INTEGER NOT NULL CHECK (revision > 0),
    PRIMARY KEY (tenant_id,facility_id),
    FOREIGN KEY (tenant_id,facility_id,fingerprint)
        REFERENCES triage_policy_artifact (tenant_id,facility_id,fingerprint)
);
CREATE TABLE triage_policy_activation_history (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    facility_id UUID NOT NULL,
    revision INTEGER NOT NULL,
    fingerprint CHAR(64),
    operator_id UUID NOT NULL,
    reason_code VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (tenant_id,facility_id,revision),
    FOREIGN KEY (tenant_id,facility_id,fingerprint)
        REFERENCES triage_policy_artifact (tenant_id,facility_id,fingerprint)
);
CREATE TRIGGER triage_policy_artifact_immutable BEFORE UPDATE OR DELETE ON triage_policy_artifact
FOR EACH ROW EXECUTE FUNCTION reject_triage_history_mutation();
CREATE TRIGGER triage_policy_activation_immutable BEFORE UPDATE OR DELETE ON triage_policy_activation_history
FOR EACH ROW EXECUTE FUNCTION reject_triage_history_mutation();
ALTER TABLE triage_policy_artifact ENABLE ROW LEVEL SECURITY;
ALTER TABLE triage_policy_artifact FORCE ROW LEVEL SECURITY;
ALTER TABLE triage_active_policy ENABLE ROW LEVEL SECURITY;
ALTER TABLE triage_active_policy FORCE ROW LEVEL SECURITY;
ALTER TABLE triage_policy_activation_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE triage_policy_activation_history FORCE ROW LEVEL SECURITY;
CREATE POLICY triage_policy_artifact_tenant ON triage_policy_artifact
USING (tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::UUID)
WITH CHECK (tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::UUID);
CREATE POLICY triage_active_policy_tenant ON triage_active_policy
USING (tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::UUID)
WITH CHECK (tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::UUID);
CREATE POLICY triage_policy_activation_history_tenant ON triage_policy_activation_history
USING (tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::UUID)
WITH CHECK (tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::UUID);
