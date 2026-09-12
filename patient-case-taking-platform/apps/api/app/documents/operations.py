"""PHI-free operational signals and reconciliation for the document pipeline."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

_SNAPSHOT = """
SELECT
  (SELECT COUNT(*) FROM document_registry
   WHERE tenant_id = $1 AND state = 'review_required')::INTEGER AS review_backlog,
  (SELECT COALESCE(EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - MIN(updated_at))), 0)
   FROM document_registry
   WHERE tenant_id = $1 AND state = 'review_required')::INTEGER AS oldest_review_age_seconds,
  (SELECT COUNT(*) FROM document_registry
   WHERE tenant_id = $1 AND state = 'scan_rejected')::INTEGER AS scan_rejected,
  (SELECT COUNT(*) FROM document_registry
   WHERE tenant_id = $1 AND state = 'processing_failed')::INTEGER AS processing_failed,
  (SELECT COUNT(*) FROM document_ocr_run
   WHERE tenant_id = $1 AND status = 'dead_letter')::INTEGER AS ocr_dead_letter,
  (SELECT COUNT(*) FROM document_extraction_run
   WHERE tenant_id = $1 AND status = 'dead_letter')::INTEGER AS extraction_dead_letter,
  (SELECT COUNT(*) FROM document_outbox
   WHERE tenant_id = $1 AND published_at IS NULL
     AND dead_lettered_at IS NULL)::INTEGER AS unpublished_events,
  (SELECT COUNT(*) FROM document_outbox
   WHERE tenant_id = $1 AND dead_lettered_at IS NOT NULL)::INTEGER AS event_dead_letter,
  (
    SELECT COUNT(*) FROM reviewed_document_fact AS fact
    WHERE fact.tenant_id = $1 AND fact.active AND (
      NOT EXISTS (
        SELECT 1 FROM clinical_timeline_projection AS timeline
        WHERE timeline.tenant_id = fact.tenant_id AND timeline.fact_id = fact.id
      ) OR NOT EXISTS (
        SELECT 1 FROM document_fhir_projection AS fhir
        WHERE fhir.tenant_id = fact.tenant_id AND fhir.fact_id = fact.id
      ) OR NOT EXISTS (
        SELECT 1 FROM document_search_projection AS search
        WHERE search.tenant_id = fact.tenant_id AND search.fact_id = fact.id
      )
    )
  )::INTEGER AS projection_reconciliation_issues
"""


@dataclass(frozen=True)
class DocumentOperationalSnapshot:
    review_backlog: int
    oldest_review_age_seconds: int
    scan_rejected: int
    processing_failed: int
    ocr_dead_letter: int
    extraction_dead_letter: int
    unpublished_events: int
    event_dead_letter: int
    projection_reconciliation_issues: int


class PostgresDocumentOperationsRepository:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def snapshot(self, tenant_id: UUID) -> DocumentOperationalSnapshot:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT set_config('app.tenant_id', $1, true)", str(tenant_id)
                )
                row = await connection.fetchrow(_SNAPSHOT, tenant_id)
        if row is None:
            raise RuntimeError("Document operations snapshot is unavailable")
        return DocumentOperationalSnapshot(**dict(row))
