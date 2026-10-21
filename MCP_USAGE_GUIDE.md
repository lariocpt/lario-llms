# MCP usage guide

The canonical instructions are [docs/mcp-guide.md](docs/mcp-guide.md) and its
[readable HTML version](docs/mcp-guide.html). Model lifecycle and registered
OpenCode run controls are in [docs/model-control.md](docs/model-control.md).

`lario_models` exposes only `model_status` and `model_options`. Select fixed
hardware-prefixed models directly in OpenCode; a different profile loads only
when its device is idle. Use https://models.in.drlario.org for operator On/Off,
preload and guarded cancellation. The former model-switch/start/stop MCP tools
are retired, regardless of an old mutation-enable environment setting.

Intel, image, media and encoder tools retain their separate permissions. Refer
to the canonical guide and each current source schema before invoking jobs.
