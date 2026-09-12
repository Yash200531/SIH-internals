# Clinical Platform

FastAPI modular transactional core containing patient identity, consent, encounters, clinical records, document registry and audit integration. PostgreSQL is its source of truth. It validates Clerk tokens at the boundary and performs internal facility, care-relationship, consent and purpose authorization on every request.
