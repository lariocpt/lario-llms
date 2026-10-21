# Fixed profiles and operator controls — October 21, 2026

## Delivered

- Fixed model profiles and exact OpenCode context metadata are deployed on all
  three owners/clients. Regular Geekom Smart large capacity uses Q8 K/V,
  245760 server / 241664 client tokens and five provisional slots.
- The Geekom interrupted-stream reconciliation bug was fixed and deployed.
  Same-profile work can use free slots while other requests run. Capacity and
  idle-only profile changes remain enforced.
- https://models.in.drlario.org now serves a dedicated authenticated operator
  page, replacing its Grafana redirect. It lists 11 Geekom, three Radeon and
  three RTX profiles, actual residency and active inference requests.
- On/Off, admission enable/disable, idle preload, request/run cancellation and
  Resume use owner revisions and idempotency keys. Off survives reboot.
- Each of the three OpenCode installations has distinct per-device inference
  keys. The v2 plugin supplies session/run/instance/kind identity. A restricted
  SSH helper invokes guarded exact-run interruption without editing databases.
- Agent model MCP tools are read-only status/options. Intel, image, media and
  encoder tool permissions remain separate. The Hermes fleet remains paused.
- Updated machine-setup overlays preserve unrelated providers/plugins. The
  page's non-root container has private credential binds, an XFS state directory,
  a read-only filesystem, health checks and boot reconciliation.
- Markdown and offline HTML instructions now describe fixed profiles and the
  operator page. Historical benchmarks remain unchanged apart from navigation.

## Deployment and verification

Implementation PRs: lario-llms #41, machine-setup #28, lario-home-infra #23.
The earlier reconciliation fix is lario-llms #40. These are merged into main.

The user explicitly approved brief gateway restarts. Geekom's llama-swap parent
PID remained 1600436; Radeon backend PID remained 3634388. Neither backend was
restarted or swapped during this rollout. RTX remained Off.

Actual HTTPS login, authenticated three-owner catalog aggregation and logout
passed. All three live OpenCode installations registered the v2 identity RPC.
`shared/serving/verify_control.py` verified the real container-to-host forced SSH
command and stale-run guard on all three machines using disposable idle sessions;
those test sessions were removed without inference. Host keys are pinned from
already verified SSH/local public keys; strict checking remains enabled.

`tests/check_opencode_identity.py` passed actual headers, interruption and a new
turn's stale-cancel protection against a fake model. Focused tests cover admission,
panel login/CSRF and cancellation reporting, the restricted helper, read-only MCP,
lifecycle and context routes. Three-client renderer tests pass. These checks do
not benchmark model speed, thermals or provisional Geekom concurrency.

## Explicit boundaries

The page lists active inference requests and their instrumented runs. Idle/tool
gaps are not GPU reservations. Title/generate background requests have request-only
cancellation because they can overlap later user turns. A new explicit user turn
establishes run identity for sessions that predate plugin installation.

Uninstrumented callers can have inference disconnected, but their agent is not
claimed stopped. Registered interruption does not undo completed tool effects or
kill arbitrary background/child processes. Full Hermes runner adapters, Intel
service lifecycle and media-job cancellation are later stages of the larger plan.
The existing RTX image/encoding hardware lock prevents the page from turning Off
during another workload; their current job tools remain authoritative.

Physical reboot/power-order validation and performance benchmarking were not run
while the user was actively using inference. They remain separate work.

## RAG boundary completion

A malformed collection probe found rag_api still running the pre-hardening
October 12 guard despite newer mounted source. Only that API container was
restarted. Health returned 200; list/dict collection payloads and unauthenticated
protected routes now return 403. Chroma, native Intel and GPU model services
were not restarted. The agents installer guard was aligned with the hardened
LLM source and received focused parity/security tests. Verified source files
alone had not established the behavior of the old in-memory Python module.
