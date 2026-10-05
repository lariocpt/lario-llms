# Cline local configuration

Sources live in machine-setup/shared/agents/cline.base.json, cline.mcp.json and machines/<host>/config/cline.json. Run the machine-setup agent renderer or ./setup.sh --agents on the client host.

The CLI receives ~/.cline/data/settings/providers.json and cline_mcp_settings.json. Existing providers, credentials and bookkeeping are preserved. Installed Cline extension storage is updated when present. Only the retired Intel qwen3-8b-int4 coding provider is removed.

Select geekom for Geekom coding, 7900xt for Radeon, or an RTX image profile for vision. Intel fixed services are available through the seven lario_intel MCP tools. Remote clients address bigcachy over the mesh. See [Intel tools](../intel/README.md) and [the model overview](../README.md).
