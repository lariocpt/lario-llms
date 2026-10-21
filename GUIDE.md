# Local AI fleet guide

See [models, locations and uses](docs/guide.md), the [offline model guide](docs/guide.html),
[MCP tools](docs/mcp-guide.md), and [model controls/session identity](docs/model-control.md).

Select fixed hardware-prefixed models directly in OpenCode. Devices load a
different profile only when idle; context and KV precision never follow a mutable
alias. Geekom is on l-dev-ai, Radeon 7900 XT on mini-mobile through OCuLink,
and RTX 5080 on Bigcachy. Intel has independent fixed services.

Operator controls: https://models.in.drlario.org. Ordinary model MCP tools are
read-only. Hardware `start`/`stop` commands delegate to durable On/Off; Off survives
reboot. The page additionally supports exact-run OpenCode interruption.
