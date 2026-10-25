# Model controls and OpenCode session identity

The operator page is **https://models.in.drlario.org**. Detailed telemetry remains
at [Grafana](https://grafana.in.drlario.org/d/lario-models/local-models).
The page controls the owners directly; inference does not pass through it.

## Fixed model selection

Choose a hardware-prefixed model in OpenCode. Its immutable ID fixes the weights,
context limit, KV precision and thinking effort. Arc B70 and Geekom regular Qwen
variants use Q4 weights and Q4 K/V. Compatible 128k, 256k and 512k variants share
one loaded backend per device; medium/xhigh effort is applied per request.
Existing Arc validation gates still restrict which variants may be requested.
Radeon/RTX retain their existing exclusive profiles and quantizations.

The Geekom host has two independent owners: `geekom` is the integrated Strix
Halo Vulkan GPU; `geekom7900xt` is the 20 GB Radeon attached through M.2 PCIe
4.0 x4. Radeon startup checks its physical UUID and skips serving when the dock
is absent. The integrated provider stays independent. A physical boot without
the dock is still pending; see the [verification record](geekom-egpu-verification-2026-10-25.md).

Client context is server context minus 4096 tokens. Geekom's existing 128k/256k
labels retain 122880/245760 server tokens. Its 512k variant has 524288 tokens.
**Qwen3.8 Supa** is separate: Q8 weights, Q8 K/V, xhigh effort and
245760 server / 241664 client tokens, with one inference slot.

The shared regular context pool ceilings are 1572864 tokens/up to ten requests
on Geekom and 655360 tokens/up to five requests on Arc. At load time the owner
measures free AMD GTT/system RAM or xe VRAM, subtracts weight/runtime/safety
reserves, and sizes the KV pool from that headroom, rounded down to 4096 tokens.
Missing telemetry refuses loading. A smaller live pool refuses larger choices;
it never reduces an active request's allocation. Each active inference
reserves its selected full context; allocation is released after the request,
not held by an idle conversation. Over-budget selections are disabled on the
operator page and refused atomically by the owner. Existing allocations never
shrink. Rendered prompts are tokenized before forwarding; input plus bounded
output must fit the selected client limit. Multi-completion and unsupported
shared-pool endpoints are refused rather than undercharging their context.

Resident memory is charged once per backend. Geekom's calculated regular/Supa
allocations are 49.1/41.8 GiB within a 105 GiB pool with an 8 GiB shared reserve.
Regular is approximately 16.35 GiB weights + 28.69 GiB attention KV + 4 GiB
runtime allowance; Supa is 29.30 + 8.47 + 4 GiB. Arc reserves 31.81 GiB against
31.890625 GiB measured capacity, including its previous 3.5 GiB runtime allowance.
These are conservative calculation inputs, **not measured peak-memory claims**.
Flash variants share one exclusive Q3/Q8 backend with 786432 pooled tokens, six
stream slots and two interactive reservations. Its 131072/245760-token windows
can mix without reloading weights; balanced is a compatibility alias. This fixed
geometry retains the previous six-slot 128k total allocation; unified-KV hybrid
runtime validation remains pending. Flash retains native scaling and its existing
thinking defaults. No linear KV memory estimate is assumed for its hybrid state.
Unbudgeted Flash/Muse/experimental backends remain exclusive; unload them before
loading another backend. `unload --profile <id>` releases the shared backend
only when none of its variants is active. Loading another model never evicts
existing work automatically.

The shared configuration uses unified KV and common 2x YaRN for regular Qwen;
Supa retains native context. Full-context Q4-cache quality and the new shared
runtime geometry require hardware validation before deployment. No service
restart or claim of production activation is implied by these source changes.

On 2026-10-26 the Flash shared backend configuration was deployed, but the first
load was interrupted by a host data-fabric sync-flood reset. All Flash routes
were then disabled through the owner controls; regular Qwen remains available.
Mixed-window inference is unvalidated. Similar platform resets and external
RX 7900 XT bus-loss errors predate this change. See the
[investigation record](../research/geekom-flash-shared-smoke-20261026.json).

## Operator controls

| Control | Effect |
| --- | --- |
| Turn on | Clear durable Off and start serving cold; inference loads a selected profile |
| Turn off | Refuse busy inference or a hardware workload lock, then stop owned serving; Off survives reboot |
| Load when idle | Preload that exact enabled profile; refuse busy, paused or Off hardware |
| Load / Unload shared backend | Load within the resident budget, or release an idle backend and all compatible variants |
| Enable / Disable | Permit/refuse new inference for a profile; disabling a busy device is refused |
| Cancel run | Tombstone that registered run, disconnect its inference and request an exact-run OpenCode interruption |
| Cancel request | Disconnect inference from a caller without trusted run control; do not claim its agent stopped |
| Cancel inference | Cancel the snapshot of active inference and attempt registered run interruption; keep admission paused |
| Cancel and turn off | Cancel tracked inference and stop owned serving; refuse another workload's hardware lock |
| Resume | Reopen admission after cancellation; it does not override Off |

Enable/disable controls admission; use Turn off to release the serving runtime.
All mutations require a fresh owner revision and an idempotency key. A stale
page refreshes rather than forcing a change. Offline/stale status is not proof
that a device stopped. Controls are disabled after ten seconds without fresh data.

The current page covers chat/vision serving and their tracked inference requests.
Image/encoder jobs retain their existing tools and hardware lock: the page refuses
Off while they hold the device instead of falsely declaring it available. Intel
service lifecycle and synchronous OpenVINO job cancellation are separate work.
An idle/tool-running conversation is not an inference reservation and is not listed
as an active inference request. Cancellation does not undo completed tool effects
or kill arbitrary background processes or unrelated child conversations.

## Identity and cancellation safety

Each development installation has a distinct inference key for each device.
The owner derives the client from that authenticated key, never from a claimed
hostname header. Existing shared role keys remain accepted for other callers but
cannot establish registered OpenCode identity.

The v2 plugin attaches conversation ID, current user-message/run ID, plugin
instance ID, conversation title, location and request kind. Titles and run metadata
are visible only after operator login. Retries and tool continuations retain
their run identity; a new user turn gets a different one. Primary, title,
compaction and generation requests can be distinguished without logging content.
Background title/generate requests have session identity but request-only
cancellation, because they can overlap a newer user turn.
Requests that began before plugin installation may lack run identity until a
new explicit user turn. They remain usable and are labelled uninstrumented.

The page uses a dedicated SSH key with a forced command and forwarding disabled.
machine-setup's helper accepts only exact-run control for an existing OpenCode
session at its recorded location. It calls the supported plugin RPC; it neither
edits OpenCode databases nor exposes OpenCode's general management API.

The plugin compares both current run and instance immediately before interruption.
It places a synchronous cancellation barrier before awaiting OpenCode's interrupt
with `resume:false`. New turns during that barrier are refused with a retry
message. Stale run/instance actions cannot interrupt a newer turn. Conversations
are preserved. The page reports `interrupted`, `idle`, `stale_run`, `stopping`,
`unsupported` or `unconfirmed`, rather than treating network failure as success.
Uninstrumented Hermes/other callers receive inference cancellation only. This
rollout does not restart or resume the parked Hermes fleet.

## Credentials, installation and recovery

The login username is `lario`. Retrieve the initial password privately on Bigcachy:

```sh
cat ~/.config/lario-model-control/operator-password
```

The non-root container receives only its operator hash, owner management keys,
restricted SSH key and pinned known-hosts file. The browser receives none of those
credentials. Login uses private server-side sessions, Secure/HttpOnly/SameSite
cookies, CSRF/origin checks and bounded failures. Sessions/audit state and owner
policy live privately on XFS, outside Git. No prompts, responses or inference
authorization headers are stored by the control page.

Source ownership:

- lario-llms: `shared/serving`, fixed catalog/gateway, page, plugin and tests.
- machine-setup: three client overlays, read-only model MCP, restricted helper.
- lario-home-infra: private compose deployment, boot reconciliation and Caddy route.

Provisioning is repeatable and preserves existing private credentials:

```sh
cd ~/Projects/personal/lario-llms
python shared/serving/provision_control.py prepare
# After the updated owner gateways are running:
python shared/serving/provision_control.py install
```

The latter installs scoped keys only after all gateways accept them, installs
the forced-command public key, renders client sources and reloads OpenCode.
The plugin has no runtime dependency downloads. Its development API dependency
is pinned to `@opencode/plugin` 2.0.22.

For a stale Geekom/Radeon client credential, run on l-dev-ai:

```sh
python3 scripts/repair_geekom_clients.py --complete
```

This reuses each development machine's registered interactive keys, verifies
them before replacement, backs up private client files, and renders the
machine-setup configurations. It never rotates owner keys or restarts model
services. Reload OpenCode with its supported `opencode reload` command on each
machine afterwards. A completion probe can share an already resident pool with
spare capacity; busy exclusive devices and draining owners defer the probe.

If the page fails, owner CLI remains available:

```sh
python shared/serving/control.py geekom status
python shared/serving/control.py geekom catalog
python shared/serving/control.py geekom activate --profile '<fixed-profile-id>'
python shared/serving/control.py rtx5080 off
python shared/serving/control.py rtx5080 on
```

CLI cancellation disconnects inference only; the page also invokes registered
client run control. Repeated Off cannot be bypassed by reboot or a model request.
Owners need not boot together: the page reconnects automatically when they return.
Physical power-order testing is separate from this implementation.

## Verification

`tests/check_opencode_identity.py` runs installed OpenCode against a disposable
local fake model. It verifies actual identity headers, guarded interruption,
new-turn identity and refusal of stale cancellation without GPU inference.
`test_fixed_serving.py`, `test_model_panel.py`, `test_model_client_control.py`
cover admission/reconciliation, credential identity, lifecycle contention,
login/CSRF, truthful cancellation reporting and the restricted helper.

`shared/serving/verify_control.py` also checks the deployed container-to-client
forced SSH command and stale-run guard on all three hosts with disposable idle
sessions; it creates no model inference.

The plugin interfaces were checked against the installed package and official
[OpenCode v2 plugin hooks](https://dev.opencode.ai/v2/docs/build/plugins/) and
[plugin RPC documentation](https://dev.opencode.ai/v2/docs/build/plugins/rpc/).
