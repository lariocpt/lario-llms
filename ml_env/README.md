# RAG access and publication boundary

`rag_api` exposes shared logical KB retrieval to serving agents and protects raw
storage, embedding and ingestion with a private host maintenance token. The
publication mapper selects and verifies immutable generations. This API keeps
the existing BAAI/bge-m3 embedding space: normalized CLS vectors, 1024 dimensions
and the native Intel CPU service's 8192-token input window.

| Interface | Access and behavior |
| --- | --- |
| `GET /health`, `/docs`, `/openapi.json` | Public service information |
| `POST /retrieve`, `/query` | Public only for the exact shared names in `scripts/rag_access.py`; private and physical collection names require the maintenance token |
| `POST /embed`, `/ingest` | Maintenance token required; ingestion supplies BGE-M3 embeddings before adding documents |
| `GET /chroma/.../collections`, `GET /chroma/.../collections/<id>/count` | Authenticated collection listing/count |
| `POST /chroma/.../collections`, `POST /chroma/.../collections/<id>/add` | Authenticated collection creation/addition; no delete, upsert or query proxy |

The storage prefix above is
`/chroma/api/v2/tenants/default_tenant/databases/default_database`.
Trusted calls use `Authorization: Bearer <KB_BACKEND_TOKEN>`. Serving agents do
not receive this token. Logical `/query` responses retain generation/scope
information alongside their answer and sources.

Public retrieval asks `KB_MAPPING_URL/retrieve` first. Legacy reads are allowed
only for the mapper's explicit `404` response with
`error: "scope has no active generation"` and `legacy_allowed: true`.
An unavailable mapper, ordinary 404, malformed response, different scope or
invalid active generation returns 503. These failures never silently return
legacy evidence. Missing raw collections return 404; storage failures return
503. Retrieval never creates a collection.

## Deployment

Use the normal hardware-aware Compose helper in `shared/compose-files.sh`.
Chroma's existing `./chroma-data:/data` volume and loopback port 8000 remain.
Its only container network is internal `kb-storage`; RAG joins both that network
and `lario-net`. RAG's host port 8100 also remains loopback-only.

Compose requires `KB_BACKEND_TOKEN` in the private root `.env`. It must match
the agents operator's `.fleet-state/operator/backend.env`, provisioned by
`agents/deploy/install-control-services.py`. Keep the value out of source and
agent containers. The container's mapper URL is
`http://host.docker.internal:8101`; the mapper is supplied by the agents repo's
`hermes-kb-map.service`. Internal mapper/storage HTTP ignores proxy environment
variables and does not forward the maintenance credential to those services.

Updating source does not reload an already-running Python API process. Coordinate
RAG deployment with live callers; the checks below do not require a service
restart or a corpus write.

## Tests

The ASGI regression suite uses the exact installed RAG dependencies, with fake
storage, embedding, mapper and LLM clients. It starts no server, performs no
model inference and never connects to real data:

```sh
docker exec -i -e RAG_API_SCRIPTS=/app/scripts rag_api python - \
  < ml_env/tests/test_rag_api.py
```

With the CPU image's Python dependencies installed locally, use:

```sh
python3 -m unittest discover -s ml_env/tests -v
```

## Review checkpoint — 2026-10-16

All 16 isolated contract tests passed on FastAPI 0.142.2, Starlette 1.7.0,
Chroma client 1.5.9 and HTTPX 0.28.1. Enabled Compose configuration also validated.
The candidate was loaded in a separate container process for read-only checks
against the real mapper, Chroma and Intel embedding service. Public legacy
Buddha retrieval and published life-recovery/life-vault retrieval matched the
running API; the real embedding was normalized and 1024-dimensional. Private
collection reads, unauthenticated ingestion and unauthenticated embedding were
refused. No production process was restarted and no corpus was written.

**Existing availability issue:** `kb-lario-local-linux` returned 503 from both
the running API and the candidate. Its active generation matches the on-disk
operator policy. Life-recovery/life-vault are readable through the running
mapper but their generation policies differ from that on-disk registry. The
mapper started on October 12 and loads policy once at startup, indicating an
older loaded policy. A standalone restart could therefore make those currently
working generations unavailable. Recover this through a coordinated agents
publication/policy rollout, preserving citation gates and active-generation
checks. Do not bypass policy checks or enable legacy fallback on an active
failure. This source commit does not claim that publication recovery is done.

Evidence: [RAG review](../research/rag-review-20261016.json).
