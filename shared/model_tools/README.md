# Model status and guarded selection

The canonical operating instructions, prompts, arguments, client permissions,
Code Mode configuration and troubleshooting are in [docs/mcp-guide.md](../../docs/mcp-guide.md)
and its [offline HTML version](../../docs/mcp-guide.html).

`model_tools.py` is the dependency-free stdio client; `owner.py` delegates to the
existing hardware controller over local execution or existing SSH. `export_choices.py`
generates the consumer-safe `model_choices.json` catalog from hardware registries.
Vendor both client and catalog into machine-setup after changing choices.

The exporter also generates `opencode_profile_models.json`, a provider-model
fragment with exact preset routes and client context limits. Merge that fragment
into each machine-setup source overlay after deploying the matching backend
generator. It contains no endpoint or credentials. Requests such as
`qwen38-flash@balanced` exist only while that preset is rendered; they do not
silently use the smaller six-slot context after a preset switch. The authenticated
gateway additionally checks saved selection against actual running geometry.
The generic hardware aliases retain safe limits across all their models.

The profile fragment and routing are prepared and unit-tested on October 6;
their fleet deployment is pending execution-review availability. See
[the completion record](../../docs/session-summary-2026-10-06.md).

Radeon Qwen offers 128k GPU KV only; RTX Qwen offers 64k only. Geekom keeps its
large-window entries and six-slot Flash option. Read the [benchmark report](../../docs/benchmarks-2026-10-06.md)
for actual validation decisions. Status separates saved alias target from actual
residency. Owner switches require a fresh status token and explicit choice, refuse
held/active/unknown/unhealthy hardware, and preserve rollback. Consumer clients
have status/options only. No credentials are exported and OpenCode is not restarted.

Management-capable clients also expose `model_start` and `model_stop` for each
hardware alias. Obtain a fresh `lifecycle_token` from `model_status`; it is
available on a reachable owner even with its inference service stopped. Owner
routing sends Radeon actions to cachyos-mini-mobile. Both actions share the CLI
controller and hardware lock, and manual stop lasts this boot. Starting saved
experimental profiles requires `allow_experimental:true`. See the canonical
MCP guide for the exact schemas and examples.
