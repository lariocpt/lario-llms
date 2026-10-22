# Geekom — l-dev-ai

128 GiB Strix Halo unified memory with a measured 105 GiB GTT pool. Native Vulkan/RADV
llama.cpp is spawned by llama-swap's user service on :11434. The Vulkan server was rebuilt
from the existing checkout (commit `16c163d56`, build 11389) to support the Flash model's
`qwen4exp` architecture; the previous executable was stale. Flash loaded and completed a
request with 4 × 245760 context and q8 KV. No container backend is used here.

Smart uses Qwen3.8-27B Q8 weights and Medium uses Q4 weights. Flash uses Q3 shards. All use Q8 K/V. Dense slot counts remain provisional memory calculations, not throughput results. Two slots are reserved for interactive coding.

| Registry model / preset | Tokens per slot | Slots | KV |
| --- | ---: | ---: | --- |
| qwen3.8-smart / capacity | 245760 | 5 | q8_0 / q8_0 |
| qwen3.8-smart / balanced | 245760 | 4 | q8_0 / q8_0 |
| qwen3.8-smart-128k / capacity | 122880 | 10 | q8_0 / q8_0 |
| qwen3.8-smart-128k / balanced | 122880 | 6 | q8_0 / q8_0 |
| qwen3.8-medium / capacity | 245760 | 5 | q8_0 / q8_0 |
| qwen3.8-medium / balanced | 245760 | 4 | q8_0 / q8_0 |
| qwen3.8-medium-128k / capacity | 122880 | 10 | q8_0 / q8_0 |
| qwen3.8-medium-128k / balanced | 122880 | 6 | q8_0 / q8_0 |
| qwen3.8-smart / long-512k | 524288 | 3 | q8_0 / q8_0 |
| qwen3.8-medium / long-512k | 524288 | 3 | q8_0 / q8_0 |
| qwen38-flash / capacity | 245760 | 4 | q8_0 / q8_0 |
| qwen38-flash / flash-128k | 131072 | 6 | q8_0 / q8_0 |
| qwen38-flash / balanced | 245760 | 3 | q8_0 / q8_0 |

Public gateway: :11434. Private backend: localhost :11444.
Select a hardware-prefixed immutable model in OpenCode. `geekom options` lists
fixed IDs; selecting one uses idle-only owner activation. Busy hardware refuses
a different profile. Legacy inference spellings are migration pins, not mutable
aliases. Client context is server context minus 4096 tokens.

`geekom start` clears durable Off and starts cold. `geekom stop` refuses busy work
and persists Off across reboot. Weights load on demand; no startup warmup is
required. The model MCP is read-only. Operator controls are at
https://models.in.drlario.org. See [controls/session identity](../docs/model-control.md)
and the [MCP guide](../docs/mcp-guide.md).

## Storage expansion

DMI identifies l-dev-ai as GEEKOM A9 Mega. Manufacturer specifications list two
identical M.2 2280 Key-M NVMe slots, each PCIe 4.0 x4 and supporting up to 4 TB.
On 2026-10-06 Linux detected one 2 TB Crucial P310 (`CT2000P310SSD8`), so the
second slot appears available; an empty slot has not been physically confirmed.
See [GEEKOM specifications](https://help.geekompc.com/hc/en-us/articles/14887570898447-A9-Mega-Specifications)
and [host inventory](../research/geekom-storage-20261006.json).

The Smart/Medium `long-512k` profiles extend context with 2× YaRN from native
262144. OpenCode's exact client limit is 520192. Both slots are coding
reservations; no fleet capacity is advertised. These configurations are
provisional, with full-window quality and allocation validation deferred. See
[512k setup and deployment boundary](../docs/geekom-512k-profiles-2026-10-22.md).
