"""Schema-contract checks for the Phase 7 document registry migration."""

from pathlib import Path

MIGRATIONS = Path(__file__).parents[1] / "migrations"


def test_document_registry_migration_has_tenant_idempotency_and_row_security() -> None:
    sql = (MIGRATIONS / "0001_phase7_documents.up.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE document_registry" in sql
    assert "UNIQUE (tenant_id, idempotency_key)" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "current_setting('app.tenant_id'" in sql


def test_document_outbox_references_registry_without_clinical_payload_columns() -> None:
    sql = (MIGRATIONS / "0001_phase7_documents.up.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE document_outbox" in sql
    assert "REFERENCES document_registry" in sql
    assert "artifact_refs JSONB" in sql
    assert "raw_ocr" not in sql.lower()
    assert "document_bytes" not in sql.lower()


def test_document_registry_migration_has_a_rollback() -> None:
    sql = (MIGRATIONS / "0001_phase7_documents.down.sql").read_text(encoding="utf-8")

    assert "DROP TABLE IF EXISTS document_outbox" in sql
    assert "DROP TABLE IF EXISTS document_registry" in sql


def test_review_decisions_are_append_only_tenant_scoped_and_idempotent() -> None:
    sql = (MIGRATIONS / "0009_document_review.up.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE document_review_decision" in sql
    assert "UNIQUE (tenant_id, idempotency_key)" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "BEFORE UPDATE OR DELETE ON document_review_decision" in sql
    assert "candidate_origin IN ('extracted', 'manual')" in sql


def test_review_schema_keeps_source_geometry_without_copying_ocr_text() -> None:
    sql = (MIGRATIONS / "0009_document_review.up.sql").read_text(encoding="utf-8")

    assert "source_bbox JSONB" in sql
    assert "source_polygon JSONB" in sql
    assert "raw_source_text" not in sql
    assert "ocr_text" not in sql


def test_promotion_schema_separates_authoritative_facts_from_projections() -> None:
    sql = (MIGRATIONS / "0010_reviewed_document_facts.up.sql").read_text(
        encoding="utf-8"
    )

    assert "CREATE TABLE reviewed_document_fact" in sql
    assert "CREATE TABLE clinical_timeline_projection" in sql
    assert "CREATE TABLE document_fhir_projection" in sql
    assert "CREATE TABLE document_search_projection" in sql
    assert "CHECK (NOT clinician_confirmed_current)" in sql
    assert "UNIQUE (tenant_id, candidate_id, candidate_version)" in sql
