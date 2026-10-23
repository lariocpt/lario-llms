# Read-only fixed-model MCP

`model_tools.py` exposes `model_status` and `model_options` only. Model lifecycle
and profile activation belong to the authenticated [operator page](../../docs/model-control.md).
Legacy mutation enable flags do not restore model-changing MCP tools.

`export_choices.py` compiles consumer-safe catalog schema 2 and the OpenCode
fragment from the same immutable serving catalog. IDs include hardware, exact
context, KV precision, slots, preset and execution revision. Vendor the client
and `model_choices.json` into machine-setup together. Neither contains keys.

Status reads public sanitized owner budgets without SSH or model warmup. Unknown
and offline states are not idle. The older `owner.py` remains a compatibility
operator helper; fixed mode refuses its old mutation protocol.

See the [MCP guide](../../docs/mcp-guide.md), its
[HTML version](../../docs/mcp-guide.html), and the
[control-page guide](../../docs/model-control.md).

`model_options` also accepts `{"hardware":"arcB70"}`. The separate `prepared`
snapshot includes thirteen Q4-only choices with compact names, native contexts
and memory estimates. One verified profile is live; twelve remain gated and
marked by per-profile enabled status. Static inventory never claims ready fleet
capacity. model_status now probes all four independent owners, including Arc;
discovery cannot warm up or activate hardware.
