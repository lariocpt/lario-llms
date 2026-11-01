# Bifrost as common ingress and logging — investigation

## Decision to make

Determine whether **MaximHQ Bifrost** adds enough useful provider routing, credential management and observability to justify another runtime hop. This is a Phase 2 decision workstream, not approval to deploy Bifrost or replace owner scheduling. Compare two implemented prototypes with fake endpoints before a limited real-client pilot:

- **Baseline:** clients connect directly to owner gateways; owners emit standardized metadata to the existing central observability stack. Hosted providers remain as currently configured. Central logs and correlation do not require a gateway.
- **Candidate:** clients -> Bifrost -> public owner inference gateway -> native router; supported hosted APIs use Bifrost provider connectors. Management remains a separate path to owners. GPU scheduling, capacity reservations, durable Off and registered-run cancellation remain in owners.

Default decision is **defer production adoption until parity and benefit are demonstrated**. Complete the router migration independently. Do not put Bifrost directly in front of native private ports, or use it to load/unload models.

## Evidence and version selection

Our [retirement record](../../SESSION-CHANGES.md) states no successful Bifrost chat since August 7, recent failures and an unused container; only that container was removed. Historical deployment pinned `maximhq/bifrost:v1.6.3`. Archived [gotchas](../../history/GOTCHAS-before-2026-10-05.md) document provider-prefix stripping and unknown custom model aliases causing 400 responses. These facts justify regression tests, not a claim that current v2 has the same bugs. Do not revive the historical database/config automatically.

Research baseline for OSS HTTP transport: [transports/v2.3.2](https://github.com/maximhq/bifrost/releases/tag/transports%2Fv2.3.2), released 2026-10-20. The GitHub `releases/latest` response captured during research selected `ent-v2.3.2-base`; do not mistake that enterprise-base tag for the desired OSS transport. Pin the actual transport release, image digest, core/plugin versions and license at execution.

Release-pinned documentation: [client/logging settings](https://github.com/maximhq/bifrost/blob/transports/v2.3.2/docs/deployment-guides/config-json/client.mdx), [virtual keys](https://github.com/maximhq/bifrost/blob/transports/v2.3.2/docs/features/governance/virtual-keys.mdx). Verify runtime behavior as well as documentation. Clearly label OSS versus enterprise-only requirements in the final decision; do not assume an enterprise feature is available in the selected image.

## Workload coverage: evidence required, not assumed support

| Traffic | Investigation / acceptance condition |
| --- | --- |
| Local text/tool chat | Explicit custom OpenAI-compatible provider, unknown immutable model IDs, tool calls/results, structured output and streaming round-trip unchanged |
| Local vision | Image encodings, data URLs/projector-compatible request shape and bounded request-size behavior preserved; no image capture in logs |
| Hosted APIs | Test only actually used providers and auth methods; tool/reasoning/response fields, rate limits and errors preserved. API-key support does not prove native OAuth/account-login support |
| Embeddings/rerank | Confirm exact endpoint and dimensions/pooling/output compatibility; never change the existing bge-m3 embedding space to simplify ingress |
| Speech/audio/image APIs | Inventory real APIs first and test only documented supported transport shapes; unsupported services keep direct endpoints |
| MCP/media/encoding jobs | Not ordinary LLM inference. Keep separate unless a later explicit MCP integration has a demonstrated need; gateway coverage does not imply process/job control |
| Owner management/budget/control | Keep separate authenticated owner/control access. Do not expose through generic Bifrost routing or translate administrative mutations |

Inventory actual client installations and hosted providers from source without copying credential databases or conversations. Record a route-by-route result: supported unchanged, supported with explicit migration, or kept direct. A single gateway for compatible inference may be useful even when some services remain direct; document that boundary rather than claim universal coverage.

## Identity is the first go/no-go experiment

Existing owner identity comes from per-installation authenticated keys; role and trusted registered-run cancellation depend on it. Mapping all local traffic to one Bifrost owner key would collapse clients and may assign the wrong reservation/cancellation authority.

Prototype Bifrost virtual-key -> exact upstream owner credential mapping for two installations, each with interactive/fleet/auxiliary behavior as appropriate. Test whether the selected OSS build can choose those upstream credentials per authenticated client without using caller-controlled identity headers. No keys appear in logs. Arbitrary forwarded headers, titles or conversation IDs do not establish identity.

If that cannot be expressed safely with native supported configuration, **do not adopt Bifrost for registered local clients**. Keep direct owner access; assess hosted-only Bifrost separately. Do not add a custom Bifrost auth plugin or trust-header bypass merely to make the pilot pass. A future signed ingress identity scheme would require its own reviewed contract and is outside this initial adoption path.

Verify model naming from the client all the way through the owner. Configure explicit custom providers/model mappings; prohibit static-datasheet inference for our immutable IDs and reject unknown models. Retain the public catalog IDs and client context/capability metadata; if Bifrost requires public renaming or alters metadata, record the required client migration and do not claim transparent adoption.

Forward permitted run metadata only after client authentication and ensure the owner still binds it to the correct installation. Test exact-run cancel, stale-run refusal and clients without trusted run control. Neither a shared trace ID nor a virtual-key name substitutes for owner authorization.

## Routing, failure and operational defaults

Disable local-profile retries, cross-model fallback and response caching initially. Preserve 429 capacity refusals, 409 busy conflicts, Off/paused refusal and unknown-model errors. A request for one immutable profile must never be retried against a different device/model/context. Do not queue around an owner refusal or replay a partially streamed tool response.

Prove streaming disconnect propagates promptly to the owner and preserves occupancy reconciliation. Keep explicit timeout budgets that allow legitimate model startup and long generation while bounding dead peers. A gateway timeout is not proof that computation stopped.

Bind the pilot to loopback; expose production ingress only through the existing authenticated/private network pattern after review. Keep Bifrost admin/control interfaces unavailable to inference users and authenticate any operator interface. Verify current release auth defaults instead of carrying forward the historical unauthenticated-admin assumption. Store new secrets privately; do not reimport retired SQLite credentials.

Bifrost is an additional availability dependency. A gateway outage returns explicit unavailability; rollback changes the opted-in client's ingress back to the preserved direct route. No hidden automatic bypass that drops authentication, logging policy or admission. Logging-sink failure must not stop inference: bound queues/storage, count drops and alert on them.

## Logging design, regardless of ingress choice

Proposed initial retention: detailed metadata events **14 days**, aggregate counters/timings **90 days**. These are design defaults, not existing production policy. Keep content logging off. Optional later debugging capture is an explicit operator opt-in scoped to one route/client and at most 24 hours, with separate deletion/retention verification before enabling it.

Event fields: generated request/trace identifier, pseudonymous authenticated installation and run reference, exact public profile and owner/backend, request class, start/end time, admission outcome, queue/load/first-token/total durations when observable, upstream status/classified error, reported token usage and cancellation/reconciliation outcome. Mark missing usage/timing unknown. Do not estimate hosted cost for local hardware or count each hop as a separate billed request.

Exclude credentials, authorization/cookie headers, raw prompts/responses, tool arguments/results, titles, image/audio payloads and private file paths. Even request parameters/tool schemas/error text can contain content; allowlist structured fields rather than deleting a few known secrets after full serialization. A generated error category is preferable to storing an upstream error body.

Use one canonical inference outcome event per request with correlated per-hop spans. Owner admission/control events remain authoritative and distinct from Bifrost provider-transport timings. Aggregates should omit run IDs/high-cardinality labels and expire their identity mapping independently. Central collection can be implemented with existing observability facilities; validate exporter/collector compatibility before choosing a Bifrost connector.

**Release-pinned Bifrost content controls require separate checks:**

- `disable_content_logging: true` strips content in Bifrost's log store; it does not govern every connector.
- Set `retain_content_in_object_storage: false`; otherwise full payloads can remain stored but hidden from UI/API.
- Keep `allow_per_request_content_storage_override: false`, and ensure no virtual key overrides content logging to false.
- Each enabled connector needs its own `disable_content_logging: true`; defaults can permit content export.
- Captured headers and some connector fields such as BigQuery parameters/tools may remain outside that filter. Leave such exports disabled until an allowlisted metadata path is proven.
- Configure retention explicitly; the documented store default is 365 days. Verify deletion in stores, object storage, exports, snapshots and backups; hiding a log row is not deletion.

For the first pilot use a local store, no object-content storage and no content-bearing external connectors. A no-content guarantee is an acceptance property, not a setting name.

## Experiments, pilot and final decision

1. Run fake endpoints through direct and Bifrost paths: text, tools, vision, malformed/unknown IDs, all used protocols, error bodies, 429/409/Off, partial streams and disconnects. Compare normalized requests and public responses.
2. Prove two-client identity/reservation/cancellation separation and admin/backend non-reachability. Inject forged identity/logging headers and verify refusal or harmless treatment.
3. Inject unique canary strings in prompt, tool schema/result, error body, auth header, image and audio fields. Inspect every enabled store/export to prove metadata-only policy; test per-key/header overrides and accelerated expiry/deletion.
4. Measure proxy overhead with at least 100 non-generation fake requests and 20 streaming cases on the actual network path. Initial acceptance budget: added p95 pre-upstream overhead <=25 ms, zero protocol/identity failures, bounded memory under a stalled sink. For real models compare transport overhead separately from decode/model-start time.
5. If all gates pass and the gateway solves an observed need beyond central owner telemetry, opt in one disposable client for 48 hours after the native-router observation period. Preserve direct configuration and keys for immediate manual rollback. Expand only after a written decision; never migrate every client/provider at once.

The final ADR must state adopt/defer/reject, exact OSS build/digest, proven workload coverage, unresolved direct routes, identity design, logging dataflow/retention, measured overhead, operational cost and rollback evidence. Successful basic chat alone is insufficient. A hosted-only pilot or direct ingress with centralized metadata may be the better outcome.
