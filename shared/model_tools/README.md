# Model status and selection from OpenCode

`lario_models` is a dependency-free stdio MCP, vendored alongside its generated
choices in machine-setup. `model_status` reads actual residency, context, slots
and the saved hardware-alias target. They are separate: a concrete request on
the legacy proxy can change residency while the alias still targets the saved
selection. Status never warms a model or calls inference.

`model_options` lists exact `model@preset` choices with per-slot context, slot
count, reservations, experimental status and CPU/GPU KV placement. Choices come
from the hardware registries via `export_choices.py`; regenerate and vendor both
files after changing a registry. Discovery works without online model hosts.

On bigcachy and l-dev-ai, `model_switch` uses existing SSH access to the hardware
owner, or the local owner helper. It requires a fresh status token and an explicit
option. Experimental options require `allow_experimental=true`. The owner holds
the controller lock, checks selection/residency freshness, user holds, device
health and actual inference occupancy, then uses the existing switch/rollback
path. Unknown or active inference is refused. There is no force, sudo, weight
download, credential export or OpenCode restart. Model-host SSH permissions,
rather than a consumer model key, authorize management.

Media and mini-mobile use status-only mode. They read public budget information
after admission activation, or current legacy `/running` metadata beforehand.
That fallback cannot verify the saved alias target or occupancy and says so.
It does not receive SSH keys or model-management/backend credentials.

Example prompts in OpenCode:

- “Show the active alias models and their contexts.”
- “List the Geekom model options.”
- “Switch Geekom to Flash Next with six 128k slots.”

The same menu is available in each hardware command. `options` lists numbered
model/resource pairs; `model@preset` and `--preset` work directly:

```sh
geekom qwen38-flash@flash-128k --experimental
7900xt qwen3.8@fast-128k --experimental
rtx5080 qwen3.8@fast-64k --experimental
```

The Geekom candidate is 6 × 131072 tokens, two coding reservations and four
advisory fleet slots. It reuses Flash's three retained shards. It is experimental
until hardware/context/concurrency checks pass. Radeon Qwen offers 32k/64k/128k
GPU KV and original 262k CPU KV. RTX offers 32k/64k GPU KV and 262k CPU KV; failed
RTX 128k remains disabled. CPU comparison-only presets stay accessible by explicit
`--preset cpu-*` but are omitted from the normal menu.

OpenCode's configured model `name` supplies the picker label; its alias ID stays
stable. The MCP provides live state independently of that static label. A later
label refresher could render a private name and use the supported idle reload,
but should not restart OpenCode or present cached/offline data as current.
[OpenCode custom providers](https://docs.opencode.ai/docs/providers/).
