# Phase 2 — Native llama.cpp router integrated with Lario

## Goal, evidence and non-negotiable gate

Replace llama-swap's lifecycle/proxy role with upstream llama.cpp router mode. Preserve the Lario owner gateway as admission/control authority. The target path is client -> owner gateway -> owner-local native router -> child llama-server. If Bifrost is later accepted, insert it before owner inference gateways; it must not replace them.

Research pin: llama.cpp commit `caa8191df159f764fb0160e3d2fc6be008948aee`, captured 2026-10-26. References: [pinned server documentation](https://github.com/ggml-org/llama.cpp/blob/caa8191df159f764fb0160e3d2fc6be008948aee/tools/server/README.md#using-multiple-models), [pinned router implementation](https://github.com/ggml-org/llama.cpp/blob/caa8191df159f764fb0160e3d2fc6be008948aee/tools/server/server-models.cpp).

This pin is research evidence, not a claim that current CUDA/ROCm/SYCL/Vulkan binaries contain those features or support every currently selected model. At execution, choose an exact upstream revision supported by each runtime and reproduce the required build/backend. If a currently necessary custom model-engine feature has no upstream equivalent, keep that owner on Phase 1 and document the blocker. No new router fork, lossy feature substitution or silent model change.

## A. Isolate backend behavior behind one adapter

Add a shared backend module, initially used with swap only, and inject it into coordinator/modelctl/runtime consumers. Proposed engine selector: owner environment `LARIO_MODEL_ENGINE=swap|native`; missing means `swap`, invalid values fail startup. This is a new interface to implement, not an existing environment option.

Minimum internal async contract:

| Operation | Required normalized behavior |
| --- | --- |
| `list_residents()` | Backend ID, normalized state, runtime argv, observed generation/fingerprint, runtime context/slot/cache geometry and validated private endpoint if available |
| `load(backend_id, generation)` | Explicit load of a known enabled backend after owner resource reservation; complete only after readiness/geometry verification |
| `unload(backend_id, generation)` | Exact idle backend, no unrelated eviction; return only after disappearance is confirmed |
| `slots(backend_id, generation)` | Real slot list with processing booleans, independent of inference capacity and without autoload |
| `backend_json(backend_id, path, body)` | Allowlisted model-scoped template/tokenizer/KV maintenance calls; no unrestricted passthrough |
| `stream(backend_id, path, body)` | Preserve status/errors, SSE framing and disconnect propagation; no buffering/replay |

Represent unknown/loading/failed/stopping/sleeping distinctly. A changing child generation invalidates stale slot results and pending mutations. Runtime status fields do not prove occupancy; real slots remain necessary. Proposed normalized types are internal only: public budgets, catalogs, operations and error semantics remain compatible.

Adapt both fixed and shared coordinators, modelctl resident/budget helpers, owner tools, container monitoring, lifecycle/deploy code, warmup scripts and monitoring consumers. Search the repository and machine-setup/agent consumers for `/running`, `/upstream`, `/api/models`, raw swap paths and process-name checks. Keep a checklist until every production caller is migrated. Older inactive paths must either use the adapter or fail explicitly when the native engine is selected.

Run existing tests with the swap adapter first. This refactor must not alter profile IDs, request admission or runtime behavior. Add engine selection outside public profile identity hashing; runtime artifact metadata belongs in separate deployment state. Retain declared model binary/image semantics until an explicitly reviewed model-profile migration.

## B. Configure an owner-local upstream router

Use one router for each hardware owner and runtime executable/backend family. The pinned implementation resolves its own executable and renders child argv from presets; it does not expose llama-swap's arbitrary per-model shell command interface. Do not assume one CUDA router can launch a different SYCL/Vulkan/ROCm binary. Preserve rootless-container namespaces and library compatibility; place ROCm/CUDA container routers in their existing container boundary.

Generate an INI from registry/backend definitions, with one preset per **internal backend ID**, not one per public context/thinking variant. Gateway routing continues to map public immutable IDs to those backends and apply request-specific thinking/context limits. Keep absolute model/projector/drafter paths valid inside each runtime namespace.

Proposed launch settings, verified as supported at the research pin:

- Launch without a model argument, with a generated `--models-preset` file and authenticated loopback listener on the owner's existing private backend port.
- Set `--no-models-autoload`; owner code calls explicit `/models/load`. Append `autoload=false` to model-scoped inference/monitor calls, reject client query overrides, and keep `load-on-startup` false.
- Set `--models-max 0` so the default count-based LRU cap cannot evict a different resident. The pinned documentation defines zero as unlimited; **Lario**, not this flag, enforces memory and coexistence limits.
- Keep automatic sleep disabled (`--sleep-idle-seconds -1`) and preserve explicit owner unload policy.
- Avoid global context/cache/parallel flags that override model-specific INI values. Pinned precedence is CLI > per-model preset > global preset. Assert effective child geometry after load.

Backend/management credentials remain separate from public inference keys. Router controls are not exposed through public ingress, Bifrost or browser clients. The pinned router controls some child options, including API key, host, port and alias; verify effective auth on both router and child instead of blindly copying swap CLI options.

## C. Preserve measured headroom without arbitrary wrappers

Current `headroom.launch` is not transferable as an INI command. Move the measurement/calculation/manifest portion into the owner load transaction, retaining the same formulas and limits; the native router launches the actual upstream child.

Under the same owner admission/lifecycle/workload exclusion:

1. Confirm target unloaded, all relevant residency known and requested coexistence allowed. Reserve provisional resident bytes before starting work; hold serialization until readiness/failure reconciliation.
2. Read current owner device telemetry; subtract weight/runtime/safety reserves and existing residency as the current policy requires. Compute the supported KV ceiling with existing rounding/minimum rules. Missing/ambiguous telemetry refuses loading.
3. Create a private pending manifest containing backend ID, deployment/load generation, measured memory and chosen context/allocation. Never treat a pending or previous-generation manifest as ready capacity.
4. Atomically update only the unloaded target's generated preset. Leave every resident preset unchanged. Refresh the router catalog using `GET /models?reload=1` only after tests prove this preserves unchanged resident models and their requests. Existing upstream docs warn changed/removed models can unload on refresh.
5. Explicitly load the target. Compare observed argv and runtime properties/slots with the calculated plan; promote the manifest to ready only on a match. On failure, reconcile actual residency before releasing reservation and remove/invalidate that generation's pending manifest.
6. On restart/reload/crash, reconcile manifests with observed backend identity and runtime geometry. Stale/unknown evidence blocks unsafe admission, rather than assuming the configured ceiling exists.

**Shared coexistence gate:** if the selected upstream cannot safely refresh an unloaded preset while another backend is resident, do not restart its router or unload the other model as a workaround. Keep shared owners on swap. Exclusive owners may regenerate presets and restart their router only when owner admission is drained and every child is confirmed idle/unloaded. This is an explicit compatibility blocker to resolve upstream, not permission to reduce functionality.

Moving the measurement earlier than exec changes its timing. Test concurrent external allocation, failed startup and measured peak headroom on each GPU. Existing workload locks must exclude our own competing workloads; unexpected external allocation must produce a controlled failed load, never overstate capacity or kill unrelated work.

## D. Map lifecycle, monitoring and prompt accounting

`GET /models` provides model status and argv at the research pin. Normalize only supported states; error/failed/sleeping must not become ready by name. Preserve backend IDs across load/unload and compare actual context, slots and KV precision. Probe actual `/props`/slots where argv alone does not establish effective runtime values.

Use explicit `POST /models/load` and `POST /models/unload` with JSON `model` set to the backend ID. Preserve owner authorization, revision checks, idempotency, workload exclusions and idle-only switching. No operator request directly calls native management endpoints.

For model-scoped monitoring/template/tokenizer/slot operations, the pinned router dispatches GETs using `model` query and POSTs using body `model`; preserve `action=erase` while adding model/autoload parameters. Verify each exact route against the selected build. Request-body routing must not replace a public profile's request semantics with an untrusted user backend ID.

Prefer authenticated model-scoped router monitoring with autoload disabled when it remains available under maximum inference occupancy. If unavailable, retain a private namespace-aware child monitoring adapter. Derive endpoints only from trusted, validated observed argv/process state, constrain to loopback and the owned process/container, and recheck generation before and after reads. No arbitrary URL derived from a client or stale manifest, no publishing child ports.

Shared prompt budgeting must still render templates and tokenize actual text/tools/images with the intended child backend. Test missing/unsupported apply-template responses, projector behavior and token budget refusal. Idle KV erase requires all slots confirmed idle and matching erase acknowledgements; failure leaves accounting uncertain and prevents unsafe allocation.

Hold request allocations through final SSE/error or verified disconnect reconciliation. Implementing native explicit load must not bypass existing pending/loading accounting or interactive reservations. Exact registered OpenCode run cancellation stays in our control plane; inference disconnect does not prove the originating agent stopped.

## E. Implementation sequence and cutover

1. Add adapter/types/engine selector with swap parity and fake-backend tests; leave all owners on swap.
2. Build and inspect the pinned upstream routers for each runtime family. Add native adapter, INI generator and artifact provenance; test protocol and child argv without production weights.
3. Refactor headroom and manifests; complete safe refresh, generation, telemetry-race and crash-recovery tests. Prove shared coexistence before enabling it on any owner.
4. Wire deploy/startup/Off/workload guards and container monitors to engine selection. Preserve public ports/keys and metadata; ensure a new engine cannot autostart an Off device after reboot.
5. Run the complete native acceptance matrix on the first eligible idle native owner; then container and shared owners. Use the guarded transaction and rollout order in the validation document. Each switch is an explicit deploy, not an automatic runtime fallback.
6. After every owner is accepted and the observation period passes, remove swap-specific production dependencies and obsolete generation paths. Retain archived rollback artifacts and document the retired state. Do not remove swap if even one production owner still needs it.

A backend failure returns the established unavailable/error state. Do not silently fall back from native to swap during a request: both could load the same weights and violate memory accounting. Rollback is an idle/drained owner transaction restoring the Phase 1 engine/artifact/config, followed by residency and policy checks.

Bifrost evaluation can run with fake endpoints while these steps proceed, but any real Bifrost pilot follows native-router stability and has a separate reversible client-ingress switch. See the Bifrost investigation for its independent decision gates.
