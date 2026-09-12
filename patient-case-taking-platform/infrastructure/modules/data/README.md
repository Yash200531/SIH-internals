# Data Module

PostgreSQL for transactional/clinical truth, MongoDB for raw transcript/OCR/model artifacts, Redis for ephemeral state, S3-compatible object storage for binaries and Elasticsearch for rebuildable search/analytics projections. Every store requires backup, encryption, residency, retention and recovery controls appropriate to PHI.
