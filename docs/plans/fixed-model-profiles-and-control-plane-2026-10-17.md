# Fixed model profiles and hardware controls

Implementation specification, 2026-10-17. **Staged implementation.**
The fixed chat profiles, operator page and OpenCode identity work are described
in [the current implementation guide](../model-control.md). Intel lifecycle,
full image/encoding job cancellation and Hermes runner adapters remain separate
stages; this specification is not a claim that every stage is deployed. This replaces
the earlier conversational plan and includes the subsequent MCP and Gaming/Off
decisions. Saving this document does not authorize interrupting current inference.

## 1. Outcome and agreed behavior

Every selectable chat/vision configuration has a fixed model ID and accurate
OpenCode context metadata. Selecting it requests those weights and that exact
configuration, independently of what previously occupied the hardware.

- Automatically load a different profile only when the device is idle.
- Refuse conflicting work while busy; do not queue a different profile for later.
- Idle conversations and pauses between inference requests do not reserve a GPU.
- Show all retained capacity/balanced profiles, distinguishing their slot counts.
- Preserve current exact context sizes. Do not turn 122880/245760 into
  131072/262144 during this project.
- Replace the redirect at `models.in.drlario.org` with an operator-login control
  page. Link to the existing Grafana dashboard for detailed monitoring.
- Cover chat, vision, image generation, encoding and Intel workloads in stages.
- Cancel active runs without deleting conversations. Keep a device paused after
  Cancel all until explicitly resumed.
- Hardware Off persists across reboot and blocks every managed activation path.
  Busy Off refuses; a separate confirmed **Cancel runs and turn off** is provided.
- Remove model-changing and lifecycle MCP tools from ordinary agents after the
  replacements work. Retain read-only model status and catalog tools.

The implementation must not claim that more concurrent slots improve throughput.
The recently calculated Geekom dense Q8 slot counts remain provisional.

## 2. Existing foundations and defects to address

Reuse the hardware registries, `shared/admission`, owner controller, GPU identity
checks, service units, model-tools exporter, machine-setup renderer and existing
image/encoding controllers. Do not introduce another general inference proxy.

Current behavior that must change:

1. Admission counts requests by role but has no request/run registry. It rejects
   nonresident models rather than loading them safely.
2. Mutable aliases and model-only IDs conceal different context/slot geometries.
3. Only selected profiles are exported to OpenCode.
4. The machine-setup renderer applies private `context_limits` with `min(...)`.
   Those private values can silently preserve the early-compaction bug even after
   source model metadata is corrected.
5. Geekom still requires production admission activation and bypass verification;
   old README statements about all gateways being inactive are stale. Determine
   live state from services/listeners before deployment.
6. Existing manual-stop intent is boot-local. Gaming/Off needs durable owner state.
7. RTX image and encoding jobs already share its hardware lock. They must join the
   same scheduler/state model as chat, including their cleanup/restore paths.
8. OpenCode versions differ: Bigcachy was 2.0.22 and mini-mobile 2.0.31 during
   inspection. The globally installed legacy plugin package is not evidence that
   a v2 integration works. Prove the actual installed-version interfaces.

## 3. Catalog and identity contract

Add a versioned catalog compiler in lario-llms. Its inputs remain the authoritative
hardware registries and existing workload manifests. Outputs are the owner routing
catalog, consumer-safe MCP catalog and generated OpenCode provider models.

Each chat profile records:

| Field | Meaning |
| --- | --- |
| `id` | Stable, globally unique fixed profile ID |
| `hardware`, `owner` | Physical resource and registered host |
| `model`, `preset`, `artifact_id` | Registry selection and pinned weight identity |
| `context_tokens`, `slots`, `reserved_slots` | Exact per-request geometry and budget |
| `kv_k`, `kv_v`, `weight_quantization` | Explicit precision; unknown values are not guessed |
| `modalities`, `output_limit` | Verified capabilities and current output ceiling |
| `execution_revision` | Digest of arguments, artifact identity and runtime configuration |
| `validation` | Validated/provisional/unsupported status and evidence links |

Use deterministic IDs containing hardware, model, context, KV precision, slots,
preset and an identity revision. Example:
`geekom.qwen38-smart.c245760.k8v8.s5.capacity.v1`.
Changing context, precision, weights or slots creates a new ID; never silently
reinterpret an existing ID. An execution-only change still changes its revision
and invalidates outstanding operation tokens. Disabled IDs remain recognizable
but cannot admit inference; retired IDs return an explicit error and replacements.

Display example:
**Geekom — Qwen3.8 Smart · 256k class · KV8 · Q8 weights · 5 slots · Capacity**.
The profile details immediately show **245,760 server tokens / 241,664 client
tokens**. Use “class” where the nominal name differs from the actual allocation.

Keep provider groups `geekom`, `7900xt`, `rtx5080`, but remove their mutable model
entries. Generate all fixed chat/vision entries. Tool-only workloads appear in
the control page and their tool catalogs, not as fake chat models.

Generate client context as `context_tokens - 4096`; keep the current profile's
output ceiling. Verify the installed OpenCode version's compaction/output
accounting rather than labelling this margin an additional output allowance.

Private client fragments become credentials/identity only. Migrate old managed
`context_limits` out of them and remove the renderer's implicit downward clamp
for the new IDs. An intentional future client cap must be explicit, visible and
separate from model capacity. Preserve unrelated providers and private settings.

## 4. Owner coordinator and request admission

Each owner runs its admission gateway even when the inference backend is off.
Extend that gateway with a coordinator and private durable state. The central
website observes and commands owners; it is not in the inference data path.

Separate desired policy from observed execution:

- Desired policy: `enabled` or `off`; per-profile enable/approval records.
- Execution: `cold`, `loading`, `ready`, `busy`, `paused`, `stopping`, `off`,
  `reconciling`, `fault`, or `hardware_absent`.
- `offline` is a remote observer's connectivity assessment, not an owner claim
  that its GPU or processes have stopped.

Use owner-local SQLite for policy, revisions, operations, audit records and
cancelled-run tombstones, outside Git with private permissions on the model XFS
storage. Keep live transport/task handles in memory. State loss or corruption
fails closed. Startup reconciles actual processes before accepting work; it
never restores a persisted active-request count as proof of running inference.

### Inference sequence

1. Authenticate the client, resolve the exact profile, validate capability and
   request shape, and check durable Off, profile disable and cancellation records.
2. Under the coordinator lock, reserve admission or create one activation
   operation. Reserve capacity for requests waiting on that activation too.
3. If the exact revision is resident, admit within the existing role reservations.
4. If idle, acquire the shared hardware transition lock, close admission, verify
   backend occupancy, load the exact profile and verify actual context/slots/KV
   arguments and runtime identity. Then admit the waiting request.
5. Same-profile arrivals may join that single bounded activation up to their
   permitted capacity. A different target during loading/busy returns conflict.
6. A disconnect removes that request's reservation. A started activation finishes
   or rolls back safely; disconnection must not leave an orphan switch or cause a
   second simultaneous load.

All CLI, dashboard, image and encoder operations enter the coordinator. Retain
the existing hardware `flock` as the cross-process guard. Refactor the controller
into a worker that does not call the gateway's drain/resume API while holding a
gateway lock. Do not nest-acquire the same lock from image/encoder adapters.

The coordinator owns profile activation from admission closure through rollback.
Never hold its short accounting lock across slow GPU work, SSH or HTTP callbacks.
Backend workers execute fixed argument lists with registered IDs, not shell
strings supplied by clients. The gateway stays available during backend restarts.

Set the initial cold-load deadline to the existing 1,800-second warmup budget;
set managed clients' first-response timeout above it with 30 seconds of transport
margin. Bound joined requests and memory use by admitted capacity. Do not emit
fake completion chunks to keep a request alive. The page receives loading events
independently. A cancelled initiating request does not reserve the GPU forever.

Failures restore the previous profile when safe. Admission stays closed until
residency and backend idleness are proven. Unknown/orphan backend work is reported
as reconciling and blocks automatic switching.

### Responses and retries

Return OpenAI-compatible error objects with stable `code`, hardware, requested
profile, resident profile and operation ID where relevant. Do not include prompts
or other users' session details in inference errors.

| Condition | HTTP | Managed client behavior |
| --- | ---: | --- |
| Different profile busy/loading | 409 | Explain conflict; no automatic retry loop |
| Stale control revision | 409 | Refresh state before another operator action |
| Off, disabled profile, paused, cancelled run | 423 | Terminal until explicit action/new run |
| Same-profile capacity exhausted | 429 | Bounded existing backoff; honor Retry-After |
| Host/device unavailable or reconciliation | 503 | Bounded retry; never switch to another model |
| Unknown/retired profile | 404 | Explain replacement; no alias fallback |
| Activation deadline exceeded | 504 | Report operation outcome; reconcile before retry |

HTTP status cannot be changed after a stream begins. Cancellation closes the
stream without fabricating a successful terminal result; the client integration
recognizes the cancellation state and suppresses automatic continuation.

Keep `/budget` compatible for lario-fleet while adding exact `profile_id`, state
and revision. Preserve reservation classes and the Hermes minimum-context rule.
Expose resident capacity separately from hypothetical catalog capacity. Off,
loading, fault and unknown state advertise zero currently available fleet slots.

## 5. Session identity and cancellation

Use distinct registered client credentials, scoped to the existing role classes.
Credentials identify the client installation; session/run headers only identify
work within that client. Shared role keys alone cannot authenticate client-host
identity. Inventory and migrate OpenCode, Hermes, RAG and auxiliary callers before
retiring shared keys.

The OpenCode integration attaches client instance, session, run and request IDs
and request kind (`primary`, `compaction`, `title`, `generate`). A run ID covers
one user-triggered agent run and its tool/inference loop; a later explicit user
turn creates a new run ID. Track auxiliary requests under their owning run.
Use the installed v2 plugin interfaces, with compatibility checks for both current
versions. Keep local providers on HTTP streaming for this implementation.

Implement a small client-side control helper, provisioned by machine-setup. It
reads OpenCode through supported APIs and interrupts an exact session/run. The
dashboard calls it only on registered hosts using a restricted SSH command and
JSON stdin. Keep OpenCode credentials on their client host; do not expose its
general management API to the browser or mutate its SQLite database directly.

Before interruption, compare the expected client instance/run revision with the
current run. A late request must never cancel a newer user turn. Use the v2
session-interrupt API with resumption disabled. Verify terminal/idle state after
the call. Test parent/child runs and stop only children belonging to the selected
run; never delete the session tree.

Add equivalent adapters to the existing Hermes run controllers. Use registered
agent/job identity, not process-name matching. Where a runner cannot stop one
run, report that limitation and leave admission paused; any process/service-level
escalation must be a separate explicit operator action.

### Cancel one / Cancel all

- Cancel one tombstones the target run, interrupts its managed runner and closes
  its model requests. Other runs using the same resident profile continue.
- Cancel all first pauses hardware admission and snapshots the affected runs and
  jobs under the operation revision. Then cancel that set, including managed runs
  temporarily executing tools for the target device.
- Tombstones survive gateway restart and reject retries of the cancelled run.
  A new explicit run may proceed after device admission is resumed.
- Check actual backend idleness and job cleanup. Report `cancelling`, `cancelled`,
  `partially_cancelled` or `unconfirmed`; never turn an unreachable client into a
  success indication.
- Unknown/uninstrumented callers can have their current inference disconnected,
  but the UI must say their originating agent was not confirmed stopped.
- Cancellation does not undo external tool side effects or kill arbitrary
  background processes. Show managed jobs that remain active.

Request/run metadata may be retained for seven days, matching operational logs.
Cancelled-run tombstones remain until their client confirms terminal retirement;
if that cannot be confirmed, retain them while the credential remains valid.
Never persist prompts, responses, authorization headers or full request bodies.

## 6. Durable Off, profile enablement and workload arbitration

Hardware Off is an owner policy, not a saved model selection. Persist the intent
before shutdown work. If shutdown fails, remain Off-desired with a visible fault;
never silently re-enable admission.

- Ordinary Off refuses active work and returns the affected workload count.
- Confirmed Cancel-and-Off cancels runs/jobs, stops owned serving runtimes and
  verifies their processes have exited. Keep Off even if the UI disconnects.
- RTX Off covers chat/vision, Comfy/image generation and GPU encoding, including
  cleanup paths that currently restore the prior chat service.
- All startup units, boot warmups, CLI commands, inference requests and job
  controllers consult the durable hold. Disable independent backend autostart
  paths that can bypass owner policy. Keep the control gateway running.
- On explicitly clears Off, verifies hardware presence and enters enabled/cold.
  Load weights on demand; do not infer that On means a model is already resident.
- Profile disable refuses a busy resident profile. When idle, disabling the
  resident profile unloads it; other enabled profiles remain eligible.
- Enabling a profile permits loading; Activate is the optional explicit preload.
- Carry forward existing explicit approvals for provisional profiles at the
  exact revision. Newly introduced experimental configurations require an
  operator enable/acknowledgment before ordinary clients may load them.

Use the same RTX resource reservation for chat, image generation and encoding.
Intel services are separate workload resources: their independent CPU/iGPU/NPU
pipelines must not be serialized behind the RTX or each other unnecessarily.
Integrate request/job accounting around their existing pipeline locks. Cancelling
an HTTP request is not proof that synchronous OpenVINO compute stopped. Keep a
job active until completion, or stop its owned service for explicit Cancel-and-Off.
Show RAG dependency consequences before disabling the embedding service; do not
change the embedding model, vector dimensions or database collections here.

The page reports both owned model-process status and observed VRAM. Gaming-ready
means all managed RTX compute workloads are stopped and cannot auto-wake, not
that display/driver VRAM must equal zero. A missing sensor means unavailable
telemetry, not zero use. The OCuLink Radeon is absent when unplugged; never fall
back to the laptop iGPU.

## 7. Control APIs and website

Keep OpenAI inference paths unchanged except for fixed model IDs. Add versioned
owner management endpoints, authenticated with management credentials:

| Endpoint | Purpose |
| --- | --- |
| `GET /admin/v1/state` | Policy, execution state, revision, health and active work |
| `GET /admin/v1/catalog` | Exact profiles and per-owner availability |
| `GET /admin/v1/operations/{id}` | Progress and terminal result |
| `POST /admin/v1/operations` | Validated activate/on/off/enable/disable/cancel/resume action |

Mutations carry an idempotency key and expected state revision. Accepted work
returns 202 plus operation ID. The owner validates action-specific fields and
durably records intent before acting. Client inference keys cannot call these
endpoints; management keys cannot perform inference.

The page backend aggregates owners over their authenticated management API using
tailnet connectivity. Client run interruption uses the restricted SSH helpers.
No host or callback URL supplied in inference headers is executable control
configuration. Owner controls continue through the operator CLI if the page fails.

Implement the page in lario-llms with aiohttp and lightweight HTML/CSS/JavaScript.
Deploy a dedicated non-root container on Bigcachy's `infra-proxy` network, with
private persistent state and no published host ports. Configure Caddy in
lario-home-infra to route `models.in.drlario.org` to it. Keep Grafana and telemetry
ingestion routes intact.

Use a dedicated operator account with a salted password hash, server-side login
sessions, Secure/HttpOnly/SameSite cookies, origin/CSRF validation and login
throttling. Mount only required management/client-control credentials. Browser
code never receives inference, backend, SSH or OpenCode management secrets.

The UI has three connected views:

1. **Hardware:** state, owner, resident profile, exact context, capacity/reserved/
   busy slots, memory, temperatures, last observation, On/Off/Resume controls.
2. **Models:** searchable fixed catalog, profile details, enabled/provisional
   status, compatibility and Activate/Enable/Disable controls.
3. **Activity:** inference requests and agent runs/jobs as distinct rows; client,
   session title/ID, profile, phase, elapsed time and cancellation outcome.

Poll owners every two seconds and stream aggregate updates to browsers with SSE.
Mark observations stale after ten seconds and disable state-sensitive controls
until refreshed. Owner revision checks still decide every action. Confirm Cancel
all/Cancel-and-Off with device name and affected-run count; never optimistic-
update the UI to Off before the owner confirms completion.

Add operational metrics for activation duration/failure, busy conflicts,
cancellation outcomes and Off state. Request/session IDs belong in the protected
activity store, not high-cardinality Prometheus labels. Continue sanitized logs.

## 8. CLI, MCP and caller migration

Operator CLI surface: `models list/status`, `models activate <profile-id>`,
`models on/off <hardware>`, `models enable/disable <profile-id>`, and
`models cancel <run-id>` / `models cancel-all <hardware>` / `models resume <hardware>`.
Cancel-and-Off is an explicit option with affected-run confirmation. Existing
hardware start/stop wrappers may delegate to On/Off during migration and must
announce the new persistent semantics. Remove numbered mutable-model switching
after callers have migrated.

Retain only `model_status` and `model_options` in the agent-facing MCP. Remove
`model_switch`, `model_start`, `model_stop`, switch tokens, mutation enable flags
and unnecessary owner SSH access from ordinary MCP clients. Return exact resident
profile and availability, not an ambiguous alias target. The page and operator
CLI own destructive control; normal model requests handle idle activation.

Migration order:

1. Inventory all live/parked callers and source configs, including OpenCode
   defaults, per-agent overrides, existing sessions, Hermes, RAG, lario-fleet,
   image tools, encoders and scheduled/boot jobs. Record their exact target profile.
2. Generate a catalog and identity migration manifest. Match current backend
   geometry to an exact profile; if it matches none, do not guess or unload it.
3. Deploy owner coordinator/control APIs and per-client credentials. Activate
   Geekom's private backend/admission arrangement during an idle window. Verify
   backend ports cannot be reached directly from peer hosts.
4. Deploy client identity integration and prove cancellation on synthetic sessions.
   Test the actual installed OpenCode versions; unsupported hooks block session-
   control promotion rather than triggering an unreviewed automatic upgrade.
5. Render fixed-profile OpenCode configs on all three hosts, migrate private caps,
   reload through supported commands, and read back effective running metadata.
6. Migrate saved sessions through supported model-selection APIs at an idle
   boundary. Map legacy aliases to the explicitly recorded profile, not whatever
   happens to be resident later. Leave in-flight turns running until completion.
7. Update Hermes/RAG/fleet routing to explicit profiles. Auxiliary title/summary
   calls should use their configured fixed profile; do not introduce an automatic
   second-model choice that repeatedly evicts the main profile between tool calls.
8. Retain temporary, hidden legacy routes only as explicit immutable mappings
   during migration. Instrument their use; remove them once audited callers and
   paused/parked configurations have migrated. No permanent alias fallback.
9. Finish image/encoding/Intel integration, then remove mutating MCP tools and
   obsolete alias instructions across all clients and KB sources.

The dashboard may be unavailable without blocking owner inference. Owners boot
independently of Bigcachy, DNS availability and each other; tailnet reconnection
restores remote control. Off persists locally. No migration step resumes paused
Hermes agents without an explicit request.

## 9. Implementation sequence and acceptance gates

Deliver separately reviewable changes in this order:

1. **Catalog/compiler and renderer migration:** all fixed profiles, private-cap
   cleanup, deterministic exports and migration report; no live routing changes.
2. **Owner coordination and durable policy:** request registry, atomic activation,
   error contracts, Off/On, reconciliation and backend bypass prevention.
3. **Client/run identity and cancellation:** OpenCode/Hermes adapters, tombstones,
   protected activity reporting and installed-version compatibility evidence.
4. **Control page and Caddy deployment:** login, live states, model catalog,
   confirmations and operator actions; existing Grafana links retained.
5. **Other workloads and retirement:** RTX image/encoding/Intel controls, caller
   migration completion, alias retirement and read-only MCP deployment.
6. **Operational validation and documentation:** independent boot tests, manuals,
   merged sources, peer sync and Hermes KB publication.

Required automated tests:

- Every exported model has the correct immutable identity, context/output limits,
  modalities and labels. Private legacy caps cannot silently lower new limits.
- Concurrent first requests to one cold profile load it once; competing profiles
  cannot both load. Requests reserve capacity while activation is pending.
- Busy streams, tool pauses, cancellations, disconnects and orphan work obey the
  agreed switching rules. No locks are held across a callback that needs them.
- Duplicate/stale operator actions are idempotent or refused. An old cancellation
  cannot interrupt a newer run with the same conversation ID.
- Failed loading, process crashes and coordinator restarts reconcile safely;
  rollback does not reopen an unverified backend or clear durable Off.
- Cancelled runs cannot reclaim hardware through retries, including auxiliary
  requests. Chat histories remain intact; unresolved clients are reported honestly.
- RTX cleanup/restore paths and all boot/start paths respect Off. Native display
  VRAM and absent telemetry do not produce false Gaming-ready conclusions.
- Image/encoding jobs mutually exclude chat; Intel pipeline work is tracked until
  genuinely stopped. RAG embedding compatibility is unchanged.
- Auth/CSRF, management-versus-inference credentials, forged client identity,
  arbitrary callback destinations, direct backend access and secret leakage are
  rejected. Error text and metric labels contain no private session content.
- Browser tests cover login, profile selection, loading/conflict feedback,
  cancellation confirmations, stale/offline states and persistent Off recovery.

Live acceptance uses short synthetic sessions, one GPU at a time during agreed
idle windows. Verify a fixed 128k/large-context entry's effective OpenCode limit
and compaction behavior, switching between profiles, cancellation preserving chat,
and Off freeing managed GPU allocations. Test owners booting in either order,
central dashboard outage, gateway restart and laptop boots without its eGPU.
Do not present the new Geekom slot budget as runtime-validated until its separate
long-context/concurrency benchmark passes.

## 10. Source ownership, rollout and completion

- **lario-llms:** catalog, admission/coordinator, operator CLI, read-only MCP,
  client bridge implementation, dashboard, workload adapters and tests.
- **machine-setup:** generated model entries, identity plugin/helper deployment,
  private-fragment migration, lifecycle provisioning and client verification.
- **lario-home-infra:** control-page compose/service route, Caddy configuration
  and deployment verification. Update awsplane only if monitoring provisioning
  changes require it, using that repo's existing checks.
- **agents/Hermes repos:** explicit profile bindings, run-control adapters,
  fleet budgets, KB source updates and ingestion provenance.

Keep secrets and owner runtime state out of Git. Back up private configs before
migration and record a source/identity manifest. Roll back per owner/client rather
than restoring a mixture of old alias metadata and new routing. Once fixed IDs
are in use, rollback must retain their safety gate or refuse them explicitly;
never make them silently resolve through an old mutable alias.

Update the Markdown/HTML model guide, MCP guide, dated benchmark/deployment
record and the Hermes lario-local-linux KB. Record what was measured versus
calculated, commit the KB sources and ingest the committed generation. Update
fleet pins where applicable.

Commit and push each coherent change, create and merge its PR into the respective
main, then mesh-sync and verify the actual owner/client revision. Preserve
unrelated work. Completion requires no dangling implementation changes, no
remaining production alias callers, verified client metadata, and an explicit
record of any deferred physical tests or unsupported cancellation adapters.

## Reference checks

- [OpenCode v2 plugin request/retry/session hooks](https://opencode.ai/v2/docs/build/plugins/)
- [OpenCode v2 API, including session interrupt](https://dev.opencode.ai/v2/docs/api)
- [llama.cpp server options and APIs](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)

These upstream references guide compatibility tests; the installed binary and
local behavior remain the deployment authority.
