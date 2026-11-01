# Current state and compatibility contracts

## Evidence and boundaries

Inspected repository HEAD: `873dadc8697db971686e114b639afbf2136f7e75`, with pre-existing uncommitted B70/shared-serving work. Source observations below include that working tree; they are not proof of production deployment. Hardware transition documents and older READMEs disagree in places. Resolve live placement from the owner registry plus effective unit/container state before rollout.

The local `~/.local/bin/llama-swap -version` reports v233/083e421 built 2026-06-29. Embedded Go metadata names `github.com/mostlygeek/llama-swap` and reports an unmodified checkout. This matches upstream release provenance, but is not a cryptographic release-asset comparison and does not establish versions on remote hosts or inside existing bind mounts.

Current data path: client -> authenticated Lario owner gateway -> keyed loopback llama-swap -> llama-server child. Native and rootless-container deployments both exist. Intel OpenVINO workloads are separate services; this migration does not replace them.

## Source owner inventory

| Owner | Registry host | Public/backend port | Runtime declared in source |
| --- | --- | --- | --- |
| geekom | l-dev-ai | 11434 / 11444 | Native; `llama-server`; `llama-swap.service` |
| geekom7900xt | l-dev-ai | 11436 / 11446 | Pinned ROCm Podman image; `/app/llama-server` |
| rtx5080 | bigcachy | 11435 / 11445 | Native CUDA; `~/build/llama.cpp/build/bin/llama-server` |
| arcB70 | bigcachy | 11437 / 11447 | Native dedicated `/mnt/xfs/AI_Models/bin/llama-server-arcB70` |
| rtx3060ti | cachyos-mini-mobile | 11438 / 11448 | Pinned CUDA Podman image; `/app/llama-server` |

Read the five hardware `models.json` files for current paths and immutable image digests. Do not assume historical descriptions of B70 Vulkan versus SYCL or Radeon placement reflect the effective service. The runtime binary/build/backend is an acceptance artifact, not a choice to change during this migration.

`shared/serving/catalog.py:render_backend` generates exclusive fixed profiles. `shared/serving/pools.py:render_pools` generates shared backend entries and deliberately sets `swap: false`, `exclusive: false`; the owner, rather than swap, owns resident-memory admission. Both emit `ttl: 0` and per-backend concurrency limits. Generated YAML is not a hand-editable source.

## Dependency map

| Contract | Current caller / behavior | Native-router adaptation |
| --- | --- | --- |
| `GET /running`, `running[]` | `gateway.Coordinator.inspect`, `_load`; `shared_gateway.SharedCoordinator.inspect`; `modelctl.current`, runtime/budget utilities | Normalize `GET /models` into resident backend ID, state and validated runtime geometry; no unknown state becomes idle |
| `model`, `state`, `cmd`, `proxy` per resident | Existing inspection parses launch flags and finds the child endpoint | Native status exposes `args`, not swap's shell command. Parse argv structurally and validate identity; do not synthesize trusted geometry from the registry alone |
| Warmup chat POST | `gateway._load` triggers on-demand startup with a short completion | Native adapter uses explicit `POST /models/load`; Phase 1 retains existing behavior |
| `POST /api/models/unload/<backend>` | `shared_gateway.unload_shared` and lifecycle tooling | `POST /models/unload` with backend ID in JSON; only after owner admission and actual-slot checks |
| `GET /upstream/<backend>/slots` | Shared idle-KV cleanup; unlike ordinary inspection, still passes through swap | Native `GET /slots?model=<backend>&autoload=false`; verify dispatch, auth and behavior under full occupancy |
| `POST /upstream/<backend>/slots/<id>?action=erase` | Shared cleanup requires matching `id_slot` and integer `n_erased` | Model-scoped native slot mutation with autoload disabled, equivalent response checks and no active slots |
| `/upstream/<backend>/apply-template`, `/tokenize` | Shared `prepare_body` renders and charges real prompt tokens | Model-scoped native endpoints; exact template/vision/tool and tokenizer equivalence required |
| Direct child `GET /slots` | `modelctl.resident_slots` bypasses swap's inference semaphore | Preserve reliable monitoring while every inference slot is occupied; verify native model-scoped monitoring first |
| Container child slots | `shared/container_monitor.py` enters private namespace; validates residency before/after | Keep child ports private. Adapt namespace monitoring only if native router monitoring cannot provide required evidence |
| Inference streaming | `gateway.create_app` proxies authorized requests and retains accounting through stream completion/disconnect reconciliation | Adapter forwards streaming without buffering, extra retries or loss of cancellation |

The public gateway's inference allowlist includes `/v1/chat/completions`, `/v1/completions`, `/v1/responses`, `/v1/messages`, `/completion`; presence in the allowlist does not prove every backend/profile implements each route. Shared profiles restrict unsupported requests. Preserve current allow/refuse behavior, rather than broadening support incidentally.

Public `/budget`, `/health`, `/v1/models` and `/admin/v1/*` belong to the Lario gateway. They are **not** upstream swap contracts to replace blindly. Public `/v1/models` comes from the Lario fixed-profile catalog, not the backend's residency catalog.

## Auth, configuration and safety

Existing runtime environment includes `LARIO_ADMISSION_ENABLED`, `LARIO_FIXED_PROFILES`, `LARIO_UPSTREAM`, `LARIO_BACKEND_KEY` and registered-client configuration. Inspect deployment generators for the complete current set without printing secrets. Private owner configuration lives under `~/.config/lario-admission/`; backend key files and generated secret-bearing artifacts remain private.

Owner policies that survive both phases:

- Client identity derives from authenticated keys. User-supplied headers are not identity evidence. Management keys cannot infer, and inference clients cannot manage runtimes.
- Exact public profiles fix context/cache geometry and thinking behavior; multiple compatible public profiles can share one internal backend.
- Same-profile capacity and interactive reservations remain usable during unrelated reconciliation; unknown occupancy blocks unsafe activation.
- Resident memory is charged once, each running request reserves its selected context, and missing memory telemetry is an error.
- No silent eviction of another resident backend, no shrinking an active allocation, no experimental-profile re-enablement.
- Disconnect is not proof that backend computation ended. Cancellation and accounting wait for verified reconciliation.
- Off persists across reboot and startup guards; workload locks prevent stealing GPUs from image/media jobs.

`headroom.launch` currently measures memory immediately before child exec, adjusts `-c`, writes a private pool manifest, then execs the selected server. This behavior is a major native-router migration requirement.

## Compatibility pitfall: IDs

`catalog.profiles` hashes runtime arguments, `reg['binary']` and image into profile revisions. A runtime-path/image refactor can therefore change public IDs unintentionally. Phase 1 does not modify these identity inputs. Phase 2 must introduce engine selection outside the identity calculation and retain existing model-serving semantics. If a necessary build/model change genuinely changes those semantics, stop and treat it as a separate profile migration; do not silently reuse IDs for different geometry.

## Test anchors

Retain the admission, fixed/shared-serving, model lifecycle, serving deploy, container admission, model client control, hardware placement and RTX3060Ti boot suites. Consult actual test names at execution time. Existing fake-backend tests are essential but do not prove new upstream protocol compatibility or real GPU behavior; see the acceptance matrix.
