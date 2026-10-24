# Local AI fleet guide

See [models, locations and uses](docs/guide.md), the [offline model guide](docs/guide.html),
[MCP tools](docs/mcp-guide.md), and [model controls/session identity](docs/model-control.md).

Incoming hardware: [Geekom/laptop Radeon placements and Arc B70](docs/hardware-transition-2026-10-23.md)
records prepared Arc profiles. Radeon uses only `geekom7900xt` on l-dev-ai.

[Software upgrade state and rollback](docs/software-upgrades-2026-10-23.md) covers
the pinned llama.cpp builds, isolated PyTorch environments and matched OpenVINO patch.

Select fixed hardware-prefixed models directly in OpenCode. Devices load a
different profile only when idle; context and KV precision never follow a mutable
alias. Geekom is on l-dev-ai, Radeon 7900 XT on l-dev-ai through M.2 NVMe,
and RTX 5080 on Bigcachy. Intel has independent fixed services.

Operator controls: https://models.in.drlario.org. Ordinary model MCP tools are
read-only. Hardware `start`/`stop` commands delegate to durable On/Off; Off survives
reboot. The page additionally supports exact-run OpenCode interruption.

Display names use `gkm`, `rdn xt`, `gfc rtx`, `intel`, `b70`, with `qwen`, `smrt`
and `md`. Context/slots stay near the front. Read-only `model_options` accepts
`hardware: arcB70` for thirteen Q4-only entries, with Smart 256k/two slots now live and the other
twelve gated, including
Muse DFlash 256k/twelve, 512k/six and 1696k/two slots. See the
[B70 capacity calculation](docs/arcb70-capacity-2026-10-23.md); these are not
hardware-tested allocations or validated extended contexts.
