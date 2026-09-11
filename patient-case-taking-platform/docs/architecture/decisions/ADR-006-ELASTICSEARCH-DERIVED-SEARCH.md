# ADR-006: Select Elasticsearch for Derived Search

## Status

Accepted for planning; production sizing and licensing remain gated.

## Decision

Use Elasticsearch as the single derived search and analytics engine for clinical-document full-text search, time-bounded audit exploration, operational aggregations and optional semantic retrieval.

PostgreSQL remains the source of truth for regulated workflow and signed clinical data. MongoDB remains the flexible transcript/OCR/model-artifact store, Redis remains ephemeral, object storage holds binaries and immutable archives, and Elasticsearch projections must be rebuildable.

The cited 2025 Elastic benchmark reports a material BBQ advantage over OpenSearch FAISS for its datasets and configurations. It is vendor-produced evidence, not a universal 2–12× guarantee. Before procurement, benchmark multilingual clinical text, index/update rate, filters, recall, p95 latency, throughput, recovery, operating cost and license constraints on representative NotMID workloads.

## Consequences

- Search results always link to authoritative records and preserve tenant, facility, patient, document/page and provenance filters.
- Index-level authorization filters supplement, but never replace, application authorization.
- Raw unrestricted transcripts and binary documents are not copied into Elasticsearch by default.
- Audit retention in Elasticsearch is sized for operations; long-term evidence lives in an immutable/WORM archive under approved policy.
- Vector search is optional and cannot become unsupervised clinical decision support.

## Evidence reviewed

- [Elastic's Elasticsearch BBQ versus OpenSearch FAISS benchmark (April 2025)](https://www.elastic.co/search-labs/blog/elasticsearch-bbq-vs-opensearch-faiss)
- [Elasticsearch reference: Better Binary Quantization](https://www.elastic.co/docs/reference/elasticsearch/mapping-reference/bbq)
