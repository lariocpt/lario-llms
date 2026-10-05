# Implementation plan: hardware utilization priorities 1–4

Prepared 2026-10-05. **Planning only:** proposed values, commands and new files below are
not deployed configuration. Implement through measured, separate changes; keep recorded
baseline profiles available for rollback. Scope is Geekom headroom, GPU KV-cache options,
workload evaluation and enforced request reservations. The user requested real autostart
and boot-order testing as the final implementation stage; it has not been performed yet.

## Baseline and decisions

The hardware registries and `shared/modelctl.py` are the configuration authority.
Geekom currently offers five model profiles; Radeon and RTX each offer three. Preserve
that model inventory, retained XFS weights, hardware aliases and compatibility wrappers.
Performance presets may change resource allocation for an existing model; they do not
require another weight download or another model family.

| Observation | Evidence / qualification | Consequence |
|---|---|---|
| Every Geekom profile allocates 983040 context tokens | `geekom/models.json`: either 4 × 245760 or 8 × 122880 | The smaller per-request window does not reduce total allocation |
| Flash Next uses q8 KV; smart/medium do not explicitly specify KV types | Registry arguments | Verify their effective types from the installed binary and startup logs before changing them |
| Latest Geekom snapshot had about 9.7 GiB available RAM and 8.6 GiB swap used, with active swapping | Earlier live inspection during the configuration rating; not a new measurement | Establish a fresh baseline and identify swap devices before attributing pressure to disk or model memory |
| Shared-load Flash decode was 7.8–12.8 tokens/s; an 8649-token prompt took 29.0 s to prefill | `research/geekom-flash-next-performance.json`; other requests were active | These measurements do not establish isolated speed or long-context quality |
| Both GPU Qwen profiles use one 262144-token slot with CPU KV | Radeon and RTX registries | Preserve this capacity option and measure a smaller GPU-KV option |
| Geekom reserves two slots; RTX reserves its sole slot; Radeon reserves zero | Registries and `agents/deploy/lario-fleet.sh` | Current enabled-agent counts are advisory, not request admission control |

Intel remains CPU BGE-M3 embeddings, NPU Whisper, iGPU translation and CPU Kokoro.
Keep the existing BGE-M3 vector space and input contract. Its services must remain healthy
during the mixed-load evaluation; this plan does not reinstate Intel coding.

## Delivery order

Build the minimum benchmark/telemetry harness from priority 3 first and capture the
unchanged baseline. Then implement priority 1, priority 2, the complete priority 3
evaluation, and priority 4. Run the same workload suite after each material change.
Finish with the real reboot/autostart matrix below, after the deployed implementation
passes its workload and admission checks.

Deliver four independently reviewable changes, with priority 3's baseline harness landing
before tuning. Coordinate dependent PRs across repositories using recorded commit IDs.
Each production change requires an idle hardware server, a saved effective configuration,
real client validation and a tested return to the previous selection. Model switching must
not restart OpenCode or interrupt active Hermes sessions.

## 1. Geekom: recover memory headroom while retaining maximum windows

**Implementation.** Add validated resource presets to the Geekom registry and controller.
Keep the five existing model choices; expose a second selector for allocation, with clear
slot counts, per-slot context and fleet capacity. Proposed command interface:
`geekom switch qwen38-flash --preset balanced`; this interface does not exist yet.

| Candidate | Larger-window profiles, including Flash | 128k-named profiles | Geekom fleet allowance after two coding reservations |
|---|---:|---:|---:|
| Existing / capacity | 4 × 245760 | 8 × 122880 | 2 / 6 |
| Balanced starting candidate | 3 × 245760 | 4 × 122880 | 1 / 2 |

These are starting experiments, not promised memory savings. Flash has a different
architecture from the dense models: measure actual weight, cache, recurrent-state and
compute allocations rather than deriving savings only from token counts. If the larger
candidate still fails the headroom gate, test 2 × 245760, explicitly showing **zero** Hermes
allowance while both coding reservations remain. Do not quietly shorten the maximum
per-request window or consume the reserved capacity.

Persist the model and preset only after successful warmup. Keep old one-line selection
files readable, and make boot rendering, concrete-ID requests, `show`, `list`, `budget`,
`slots`, `context` and `reserved` use the effective preset. Generate every callable profile
consistently so a concrete model request cannot escape the chosen allocation. Roll back
the generated config, model and preset together on failure.

Before promotion, record `/proc/swaps`, `MemAvailable`, memory PSI, swap-in/out, model
RSS/PSS and backend allocation logs for idle and loaded runs. Separate cold loading from
steady inference. Do not turn off swap, clear global caches or add `mlock` as a substitute
for reducing allocation. Keep today's load mode during the first comparison.

**Promotion gate.** Initial target: at least 15 GiB available at the worst measured point
of a 30-minute representative concurrency run, preferably 20 GiB. After warmup, no
repeated swap-out pressure or memory-PSI `full` above 1% sustained for a minute. Require
complete responses, tool calls and retrieval quality at least matching baseline, and no
more than 10% median latency regression on equal-concurrency cases. Compare reduced
concurrency separately from original maximum throughput. Treat thresholds as operational
targets to confirm against actual shared host load.

**Files.** `geekom/models.json`, `shared/modelctl.py`, `tests/test_modelctl.py`,
`geekom/README.md`; machine-setup client metadata and agents fleet/KB sources if effective
capacity changes. Client context limits retain output/template headroom.

**Rollback.** Select the original capacity preset and previous model using the controller.
Prove legacy wrapper selection and boot rendering restore the original geometry.

## 2. Radeon and RTX: measure GPU KV against the maximum-context option

**Implementation.** Retain Qwen3.8 Q3 with 262144 context and CPU KV as the capacity preset
on each card. Add an experimental `fast` resource preset under that same Qwen model
choice. Keep all model weights on GPU initially; test q8 K/V with GPU KV and one slot at
32768, 65536, then 131072 context. Stop increasing when measured headroom or quality fails.
Check flags in each installed binary before generating configuration: the CUDA and ROCm
builds are different versions. q4 KV is a later experiment only if supported and the q8
results justify a quality comparison.

Require at least 1.5 GiB free RTX VRAM and 2 GiB free Radeon VRAM at measured peak load,
including compute buffers and any existing display use. These are initial operating
margins, not evidence that any candidate fits. Avoid automatic fitting that silently
changes the tested context or offload count; verify the actual effective allocation.
Test one card at a time, without assuming their identically quantized model will have
identical performance.

Compare CPU-KV and GPU-KV at **equal contexts** before comparing the fast preset with
262144 capacity. Use repeated 8k and 32k input workloads with 256–512 output tokens,
plus the common benchmark's correctness cases. Seven-token smoke responses cannot
establish a speed improvement. Record TTFT, prefill/decode throughput, latency, RAM,
VRAM and allocation logs. Preserve Muse/DFlash and the two vision modes.

**Promotion gate.** Complete five repeats per comparison, no allocation failures or
truncation, required VRAM margins, and no correctness regression. Promote only when
median TTFT or decode improves by at least 20% at equal context with the other latency
measure no more than 10% worse. Otherwise retain CPU-KV as default and publish the
measured tradeoff. Report the maximum demonstrated GPU-KV window honestly.

**Client exposure.** The existing three model choices remain primary menu entries; a
secondary preset selector chooses fast or capacity. Any additional callable preset IDs
use the same weights and must carry their actual context/image capability in OpenCode
and Hermes. The generic hardware alias remains conservative across all callable presets;
reject an oversized request explicitly. Update Hermes advertised windows together with
its endpoint/model, and expose the effective preset to fleet budgeting.

**Files.** `7900xt/models.json`, `rtx5080/models.json`, shared controller/tests, GPU READMEs,
`machine-setup/shared/agents/` and host overlays, relevant `agents/hermes/*/config.src.yaml`.

**Rollback.** Restore the previous Qwen capacity selection and client limits; warm and
run a completion. Verify returning to Muse or vision still releases the previous model.

## 3. Reproducible workload benchmarks and routing decisions

**Implementation.** Add a versioned suite under proposed `benchmarks/`: a runner, fixture
manifest, deterministic fixtures, assertions and a result schema. Store sanitized result
JSON and readable summaries under `research/benchmarks/<run-id>/`. Use temporary coding
workspaces and synthetic documents/images/audio; never collect private agent conversations
or use production document ingestion as a benchmark fixture.

| Workload | Verification | Initial scope |
|---|---|---|
| Coding | Patch a small fixture repo and pass behavior tests | At least 10 tasks, measured through real OpenCode |
| Tool use | Correct tool name, arguments, execution and follow-up answer | At least 10 cases, including invalid input and disconnected tools |
| OCR and image comparison | Exact IDs/totals and known visual differences | 12 generated pages/images, varied resolution and small text |
| Image/video-frame description | Required objects/events and false claims | 8 scenes/sequences; submit extracted frames through the existing image API |
| RAG | Expected document rank, source citation and supported answer | 10 synthetic retrieval queries in an isolated test collection, with cleanup |
| Long context | Recover facts near start/middle/end without truncation | 8k/32k/64k/128k, then a bounded near-maximum case for each advertised window |
| Mixed operation | Client completion plus healthy Intel tools/RAG | Coding with Hermes, vision/compaction and speech/translation load |

Run latency microbenchmarks five times and score each quality task individually; use
fixed inputs, sampling and output budgets, with reasoning settings recorded. Separate
cold starts, warm runs, prompt-cache reuse and cache-disabled cases. Record software
commit/version, registry/config hash, selected and resident model, effective context,
slots, KV placement/type, concurrency, usage/finish reason, TTFT, prefill/decode timings,
end-to-end latency, failures and timed RAM/VRAM/PSI/swap observations. Measure time to
first content separately from first reasoning output and protocol heartbeat.

Test one request and each advertised concurrency, plus one excess request. Shared-load
results are useful but must be labelled; establish controlled results before ranking
models. For long context, tokenize with the target backend, budget prompt/template/output
together, and keep a timeout/token ceiling. A completed short response with a large
allocation is not a full-window test. Report sample counts beside p50/p95; use a longer
mixed run with at least 30 completed comparable requests before drawing p95 conclusions.

**Promotion gate.** All contract checks pass, benchmark collection deletion is verified,
quality scores and failures are published, and each claimed context has a completed
near-limit case. At minimum: correct coding fixtures, exact tool execution, critical OCR
fields and supported RAG citations; no silent truncation. Set workload defaults from
measured results, including Muse with and without DFlash. Do not declare Flash fastest
or the current vision model universally best from existing smoke checks.

**Files.** Proposed `benchmarks/` and `research/benchmarks/`, benchmark runbook, client
validation instructions and Hermes knowledge. Keep telemetry prompt-free by default.

**Rollback.** Benchmarks themselves do not change defaults. Restore the initial model
selection after each tuning run; remove only the run's identified temporary fixtures
and test collection. Halt model-changing tests if unrelated live inference begins.

## 4. Enforce reservations at request admission

**Decision.** Enforce admission once per physical model host, in front of llama-swap.
Use a small streaming gateway unless a source audit of the installed proxy proves it
already supports authenticated workload classes with shared per-hardware accounting.
Do not create separate proxies with independent counters for the same card. Existing
per-model concurrency limits remain the final backend safeguard.

Treat reservations as protected admission capacity, not permanently assigned llama.cpp
slot IDs. Start with a strict policy: Hermes never borrows coding-reserved capacity;
interactive clients may use otherwise idle capacity, but cannot interrupt active Hermes
requests. RTX's sole slot is auxiliary capacity shared by OCR, vision and compaction;
general fleet chat remains excluded unless its hardware policy is explicitly changed.

For Geekom, total in-flight requests must be ≤ effective slots and fleet requests must
be ≤ slots minus two. Radeon uses its full effective slot count for fleet requests. A
one-slot auxiliary backend returns a retryable capacity error when occupied, rather than
silently queueing behind a potentially long request. Keep retries bounded and validate
actual OpenCode and Hermes retry behavior before rollout.

**Implementation contract.**

1. Identify interactive, fleet, auxiliary and management callers through distinct
   credentials, stored outside Git. A client-provided class header or model alias alone
   must not grant reserved capacity. Deploy client credentials through existing source
   renderers/private environment mechanisms; never log them.
2. Resolve aliases and concrete IDs to one hardware resource. Make reservation accounting
   atomic before forwarding, including streaming, non-streaming and any other callable
   inference route. Return 429 with `Retry-After` on capacity exhaustion and zero
   available capacity/503 when readiness cannot be established.
3. Reject requests that would swap models while any inference is active. Serialize an
   idle model transition and its warmup; recheck capacity afterward. Controller switching
   must use the same drain/lock mechanism. Close admission before a preset change, drain
   active work, then publish the new model/config generation atomically.
4. Hold admission until backend work actually ends. On client disconnect, cancel upstream
   and confirm slot release before reusing capacity. On gateway restart, inspect backend
   occupancy and quarantine uncertain capacity; losing in-memory counters must not permit
   oversubscription. Do not assume a disconnected TCP client means generation stopped.
5. Keep public client ports 11434/11435/11436 stable. Move downstream native listeners to
   private endpoints and remove container-DNS bypasses. In particular, `agent-llm:8080`,
   `vision:8080` and dynamically spawned llama-server ports must not let
   ordinary clients skip admission. Choose private ports after checking live listeners.
   Preserve read-only health/model discovery; protect management operations separately.
6. Publish effective model/preset, configuration generation, readiness, class limits,
   active requests and rejection counts. Change `modelctl budget` and `lario-fleet` to
   read this authoritative budget in one snapshot. Replace Geekom's separate hard-coded
   reservation parsing; environment overrides may lower a displayed limit but cannot
   enlarge server capacity. Distinguish enabled agents from currently active requests.
7. Run each gateway on its hardware owner, with mount/unit dependencies and local readiness
   recovery. It must start without its peer host. Retain offline Intel MCP discovery and
   preserve existing clients' host-address fallbacks.

**Promotion tests.** Fill the Geekom fleet allowance, prove the next fleet request gets
429, then complete two simultaneous interactive requests without exceeding total slots.
Repeat across all effective presets. Test RTX auxiliary contention, Radeon limits,
unknown credentials, aliases, concrete-ID swaps, streaming disconnect/cancellation,
upstream failures, gateway restart during inference, drain timeout and peer outages.
Prove inference cannot bypass the gate through host ports or Docker DNS. Verify actual
OpenCode/Hermes completions and tool calls before removing transitional routing.

**Files.** Proposed `shared/admission/`, policy schema and gateway tests; controller,
native units and Radeon/vision compose routing; machine-setup renderers/overlays; agents
fleet, boot and Hermes sources; infrastructure startup integration only where needed.

**Rollback.** Revert gateway listeners, unit/compose bindings and client routing as a
coordinated set after draining requests. Restore the known working advisory-budget setup
and label reservations advisory again. Preserve private credentials securely for a retry;
do not copy agent state or reset sessions during rollback.

## Final stage: real autostart and boot-order testing

Run this after priorities 1–4 are implemented, deployed and validated. This is planned
physical reboot testing, not a claim that enabled units or simulated outages prove boot
recovery. See [current boot behavior](BOOT.md) for the existing setup and evidence limits.

Before starting, save the effective model/preset, Git commits, mount identifiers, expected
units/containers and parked/enabled agent list. Drain model requests and finish active
agent work. Verify host access, Swarm manager roles/quorum and a recovery path before
shutting down hosts. Observe from an unaffected third machine or an operator console:
the coordinating process must not disappear when bigcachy restarts. Start with individual
reboots, then test both startup orders.

| Scenario | Required result |
|---|---|
| Reboot l-dev-ai while bigcachy stays up | Geekom restores its saved model/preset from XFS automatically; bigcachy local services stay healthy and remote clients recover |
| Reboot bigcachy while l-dev-ai stays up | Intel, Radeon, RTX, RAG/Chroma, configured Hermes agents and Portainer recover automatically; Geekom remains usable |
| Both down; start l-dev-ai first | Geekom loads without bigcachy; clients reconnect when bigcachy starts later |
| Both down; start bigcachy first | Local services and offline Intel MCP discovery work while Geekom is absent; remote inference recovers when l-dev-ai starts later |

For each scenario, record shutdown/start times, changed boot IDs, XFS mount readiness,
service readiness and time to first successful inference. Keep the second host off until
the first host's independent startup checks have completed; otherwise the order test does
not prove independence. Use configured cold-load deadlines rather than a short generic
HTTP timeout. Mark any deadline failure explicitly.

Verify all of the following **before manually starting or repairing a service**:

- XFS is mounted at the expected path/UUID before model loading; no fallback weight
  directory or download appears on the root filesystem.
- Saved model and resource preset match actual process arguments, context, KV placement
  and concurrency after boot. Capacity is zero until ready; admission reservations work
  after recovery and no old workload can bypass the gate.
- Each native Intel service produces a real result: compatible BGE-M3 embedding, Whisper
  transcription, translation and Kokoro audio. The selected Radeon, RTX and Geekom
  profiles complete requests; verify vision with a real image when a vision mode is selected.
- Existing Chroma data and the Hermes knowledge collection persist, retrieval returns
  the implementation record, and only previously enabled agents start. Run the existing
  agent database checks without copying live databases.
- Real OpenCode completion and an Intel MCP tool call recover; peer-dependent requests
  return a bounded unavailable/retry response while the peer is absent. Repeat the
  reservation/contention smoke check after both hosts are ready.
- Portainer server/API and expected Swarm agent replicas recover. Check restart counters
  and journals for repeated failures; observe stable operation for at least ten minutes
  after readiness.

Record results under proposed `research/boot/<run-id>/` and update `docs/BOOT.md` plus the
Hermes implementation record. A manually repaired boot is a failed autostart case: fix
the canonical sources, redeploy and repeat that scenario. Completion requires all four
scenarios to pass without manual model/service startup, with restored configuration,
persistent data and automatic client recovery.

## Completion record for each implementation change

Run relevant controller/admission tests, configuration rendering and all-host machine-setup
dry runs when its sources change. Inspect diffs for credentials and unrelated edits.
Commit only owned source/evidence paths, create PRs, merge tested changes into each main,
and mesh-sync available hosts while respecting existing opt-outs. Record offline hosts
as pending deployment rather than claiming completion.

Update `agents/hermes/lario-local-linux-agent/knowledge/04-local-llm-config.md` with actual
effective presets, measurements, reservation behavior, client checks and merged commits.
Include this canonical plan in its ingest manifest, clearly labelled proposed. Run the
real citation-gated ingest and retrieve both plan and implementation facts from
`kb-lario-local-linux`. Record what was measured versus what remains untested.

## Upstream references checked while preparing this plan

The official [llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/tree/master/tools/server)
documents context/parallel controls, KV placement/types and slot inspection. Validate
availability against the installed binaries before using newer flags.

The official [llama-swap configuration example](https://github.com/mostlygeek/llama-swap/blob/main/docs/config.example.yaml)
documents global and per-model concurrency limiting with immediate 429 responses and API
key configuration. These primitives do not alone demonstrate the workload reservation
and restart reconciliation contract proposed above.
