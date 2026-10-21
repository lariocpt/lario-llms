# Model controls and OpenCode session identity

The operator page is **https://models.in.drlario.org**. Detailed telemetry remains
at [Grafana](https://grafana.in.drlario.org/d/lario-models/local-models).
The page controls the owners directly; inference does not pass through it.

## Fixed model selection

Choose a hardware-prefixed model in OpenCode. Its immutable ID fixes the weights,
context, KV precision, slot count and preset. Selecting another profile loads it
only when its hardware is idle. A busy device refuses a different profile;
requests for the resident profile share its available slots. No cross-model queue
or fallback to a different device is used.

Client context is server context minus 4096 tokens. Regular Geekom Smart's large
capacity profile has **245760 server / 241664 client tokens, five slots and Q8
K/V**. It is the default, rather than Flash Next. Dense Geekom slot counts remain
provisional calculations; this rollout does not claim a throughput improvement.

## Operator controls

| Control | Effect |
| --- | --- |
| Turn on | Clear durable Off and start serving cold; inference loads a selected profile |
| Turn off | Refuse busy inference or a hardware workload lock, then stop owned serving; Off survives reboot |
| Load when idle | Preload that exact enabled profile; refuse busy, paused or Off hardware |
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
