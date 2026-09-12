from pathlib import Path

MIGRATIONS = Path(__file__).parents[1] / "migrations"


def test_patient_intake_migration_is_scoped_and_rollbackable() -> None:
    up = (MIGRATIONS / "0013_patient_intake_submission.up.sql").read_text()
    down = (MIGRATIONS / "0013_patient_intake_submission.down.sql").read_text()

    assert "CREATE TABLE patient_intake_submission" in up
    assert "UNIQUE (tenant_id, idempotency_key)" in up
    assert "FOREIGN KEY (tenant_id, consent_id)" in up
    assert "ENABLE ROW LEVEL SECURITY" in up
    assert "FORCE ROW LEVEL SECURITY" in up
    assert "current_setting('app.tenant_id'" in up
    assert "DROP TABLE IF EXISTS patient_intake_submission" in down
