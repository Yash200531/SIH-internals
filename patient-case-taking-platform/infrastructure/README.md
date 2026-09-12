# Infrastructure

Structure infrastructure by reusable modules and explicitly promoted environments.

- `environments/local`
- `environments/dev`
- `environments/staging`
- `environments/production`
- `modules/network`
- `modules/edge`
- `modules/compute`
- `modules/data`
- `modules/messaging`
- `modules/observability`
- `modules/secrets`
- `kubernetes/base`
- `kubernetes/overlays`
- `runbooks`

## Deployment baseline

- Docker images for Next.js apps, FastAPI services, vLLM and PyTorch workers.
- Docker Compose for local development with PostgreSQL, MongoDB, Redis, Kafka and S3-compatible storage. Elasticsearch is an optional search profile.
- Kubernetes for shared pilot and production environments, with separate CPU and GPU pools.
- CDN/WAF through CloudFront, Cloudflare or an equivalent selected by hosting constraints.
- Managed PostgreSQL, MongoDB, Redis, Kafka, object storage and Elasticsearch are preferred over hospital-local stateful clusters where residency and procurement allow.
- KServe or Ray Serve is deferred until model count, rollout frequency or distributed GPU scheduling demonstrates the need.

Infrastructure remains provider-neutral until availability, residency, cost and facility-connectivity requirements are approved. Kubernetes is a target runtime, not permission to create a service mesh or operate every dependency inside the cluster.
