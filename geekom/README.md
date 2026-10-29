# Geekom — l-dev-ai

## Flash Next extended context — 2026-10-30

Select **gkm-512k shared-qw3.8 FN Strata Q3 kv4** for the new two × 512K mode.
It uses the same Q3 weights and KV4, with explicit YaRN 2× extension. The former
four × 256K mode remains an exclusive rollback option. Allocation and short
responses are verified; full-window quality is pending. See
[configuration and evidence](../docs/flash-next-extended-context-modes-2026-10-30.md).

## Flash Next Strata — live 2026-10-27

Select **gkm-256k shared-qw3.8 FN Strata Q3 kv4** in OpenCode.
The official HIP Halo engine 0.1.50 serves the existing UD-Q3_K_XL weights with
Q4 KV and four independent 262,144-token slots. The owner gateway remains on
:11434 and enforces four full-window reservations and model exclusivity.
Regular Qwen remains available through the previous Vulkan profiles.

Application, private Python, libraries and state are under **`~/strata` on btrfs**,
alongside the older `~/llama.cpp` installation. Only weights and the prepared
pack are on XFS (`/mnt/AI_Models/strata/packs/qwen38-flash-ud-q3-k-xl`).
The launcher resolves the healthy `1002:1586` integrated GPU by PCI identity;
its bus address changed during the user's reboot. The external 7900 XT was
powered off after PCIe bus loss and is excluded from this placement.

The native four-slot test passed eight short responses over two rounds and
four authenticated public-gateway requests passed. Full-window ingestion,
quality and throughput remain unvalidated. The profile stays experimental.
Prefix reuse is preserved; idle-KV erasure is disabled for this recurrent pool.
Expert-cache allocation is explicit (6000 largest-blob budget slots), mapped
resident complements omit GPU-resident experts, prefill is 1024, and conversation
parking is bounded at 512 MiB with two prompt checkpoints. No MTP draft is loaded.

Code: `geekom/strata/`; evidence: `research/benchmarks/20261027-geekom-strata/`.
The later sections describe the older Vulkan configuration and its investigation.
For deferred performance work use
[the two-night runbook](../docs/benchmarking-qwen-b70-and-gkm-2026-10-27.md).

128 GiB Strix Halo unified memory with a measured 105 GiB GTT pool. Native Vulkan/RADV
llama.cpp is spawned by llama-swap's user service on :11434. The active Vulkan
runtime is pinned v0.7.0 (`620d2225cc436ab0b001e3200e590e3b286ef9ab`), selected
through `geekom/llama-server-vulkan` with an explicit integrated-APU guard.
Smart/Medium normal and 512k profiles plus Flash passed short responses and
native slot checks on 2026-10-23. No container backend is used here.

Regular Smart/Medium use the same Qwen3.8-27B Q4 weights and Q4 K/V, with xhigh/medium thinking per request. Supa retains Q8 weights and Q8 K/V at 245760 tokens for harder reasoning. Flash retains Q3 shards and Q8 K/V; its 131072/245760-token variants share one exclusive backend. The shared Q4 backend is live; full-window quality remains unvalidated. See [model controls](../docs/model-control.md). Two regular-pool slots are reserved for interactive coding.

| Registry model / preset | Tokens per slot | Slots | KV |
| --- | ---: | ---: | --- |
| qwen3.8-smart / capacity or balanced | 245760 | shared pool | q4_0 / q4_0 |
| qwen3.8-smart-128k / capacity or balanced | 122880 | shared pool | q4_0 / q4_0 |
| qwen3.8-medium / capacity or balanced | 245760 | shared pool | q4_0 / q4_0 |
| qwen3.8-medium-128k / capacity or balanced | 122880 | shared pool | q4_0 / q4_0 |
| qwen3.8-smart / long-512k | 524288 | shared pool | q4_0 / q4_0 |
| qwen3.8-medium / long-512k | 524288 | shared pool | q4_0 / q4_0 |
| qwen3.8-supa / capacity | 245760 | 1 | q8_0 / q8_0 |
| qwen38-flash / capacity | 245760 | shared pool | q8_0 / q8_0 |
| qwen38-flash / flash-128k | 131072 | shared pool | q8_0 / q8_0 |
| qwen38-flash / balanced | 245760 | shared pool (alias) | q8_0 / q8_0 |

Public gateway: :11434. Private backend: localhost :11444.
Select a hardware-prefixed immutable model in OpenCode. `geekom options` lists
fixed IDs. Compatible Smart/Medium variants share the resident backend, with
available capacity calculated from context reservations and stream slots.
Loading another backend obeys owner admission and memory limits. Legacy inference spellings are migration pins, not mutable
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
second slot now carries the RX 7900 XT dock. The 2026-10-25 kernel reports
PCIe 4.0 x4 for that connection. The Radeon and integrated Vulkan GPU remain
separate providers; removing the dock does not select Radeon work onto the iGPU.
See [GEEKOM specifications](https://help.geekompc.com/hc/en-us/articles/14887570898447-A9-Mega-Specifications)
and [host inventory](../research/geekom-storage-20261006.json).

The Smart/Medium `long-512k` profiles extend context with 2× YaRN from native
262144. OpenCode's exact client limit is 520192. Context reservations share
the regular Q4 pool, whose ceilings are 1572864 tokens and ten stream slots;
runtime memory headroom can reduce these. These configurations are
provisional, with full-window quality and allocation validation deferred. See
[512k setup and deployment boundary](../docs/geekom-512k-profiles-2026-10-22.md).

## Idle KV investigation — 2026-10-26

The resident regular Qwen pool retained 371313 tokens after clients stopped, but
the B70's large SYCL slowdown was not reproduced on Geekom Vulkan. Same-process,
pinned-slot controls gained only 0.6%/1.1% decode speed after erasing a 39k/80k
idle history. Four concurrent short requests took 7.61 s with a 39k idle history
versus 7.50 s after erasure. The native runtime automatically purges idle histories
when KV allocation needs space; those histories do not permanently consume
request slots or gateway reservations. Full-window maximum concurrency remains
untested. No proactive cleanup policy or permanent launcher change was justified;
the diagnostic erase capability was removed and the original resident model
configuration restored. See [measurements and fleet verification](../research/benchmarks/20261026-geekom-kv/REPORT.md).

Flash mixed-window serving was deployed on 2026-10-26, but its profiles remain
disabled after a host reset during the first load. Runtime validation is incomplete.
All three recent resets report data-fabric sync flood, including resets before
this change; the external RX 7900 XT logged PCIe bus loss. That is a platform
stability lead, not proof that Flash is working or that its new geometry caused
the reset. See the [smoke test and investigation](../research/geekom-flash-shared-smoke-20261026.json).
Its fixed pool has 786432 tokens and
six stream slots, including two reserved for interactive coding. For example,
two 245760-token requests and two 131072-token requests reserve 753664 tokens;
six 131072-token requests fill the pool. Each request reserves its full selected
window until completion. Flash keeps native context scaling and two checkpoints.
The pool remains exclusive to the integrated GPU: unload regular Qwen/Supa
before loading Flash, and unload Flash before loading another backend. Its
83.81 GiB weight shards and hybrid state require a separate measured memory
contract before coexistence or automatic headroom sizing can be enabled.
