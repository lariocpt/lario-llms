# Your local AI fleet

Choose a fixed hardware-prefixed model by task. OpenCode defaults to regular
`gkm - 240k 5 slots - qwen3.8 smrt`, large context with Q8 KV. Selecting another profile loads
it only when its device is idle. [Operator controls and session identity](model-control.md)
are at https://models.in.drlario.org; the model MCP is read-only.

Prepared upcoming placements: `gkm7900xt` on l-dev-ai, `winmax7900xt` for the
existing laptop placement until deprecation, and `arcB70` on Bigcachy alongside
the RTX. Arc has [Q4-only Qwen and Muse DFlash preparation profiles](arcb70-capacity-2026-10-23.md).
These are not yet selectable providers. See the
[hardware transition plan](hardware-transition-2026-10-23.md).

## l-dev-ai · Geekom Strix Halo

The large shared-memory host is the primary coding and reasoning server. All
weights and download caches live on its XFS model partition.

The machine is GEEKOM A9 Mega: two identical M.2 2280 PCIe 4.0 x4 storage slots.
One nominal 2 TB Crucial P310 is detected; the second slot appears available,
with physical vacancy unconfirmed. See [the storage inventory](../geekom/README.md).

| Model | What to use it for | Context and concurrency |
| --- | --- | --- |
| gkm - 240k 5 slots - qwen3.8 smrt | Coding, harder reasoning, planning and reviewing code | 245760 tokens per slot; five capacity slots or four balanced slots; calculated Q8 allocation |
| gkm - 120k 10 slots - qwen3.8 smrt | The same weights with more concurrent shorter requests | 122880 tokens per slot; ten capacity slots or six balanced slots; calculated Q8 allocation |
| gkm - 240k 5 slots - qwen3.8 md | Coding and general assistance with less weight memory | 245760 tokens per slot; five capacity slots or four balanced slots; calculated Q8 allocation |
| gkm - 120k 10 slots - qwen3.8 md | More concurrent requests using the medium quantization | 122880 tokens per slot; ten capacity slots or six balanced slots; calculated Q8 allocation |
| gkm - 512k 3 slots - qwen3.8 smrt / md | Longer coding/review sessions using 2× YaRN context extension | 524288 server / 520192 client tokens; three slots; Q8 KV; provisional, not full-window validated |
| gkm - 240k 4 slots - qwen3.8 Flash Next | Coding, tools and general work; measured on the large host | 245760 tokens per slot: four capacity or three balanced slots; a separate six-slot 131072-token choice |

The dense-model slot increases are provisional: see the
[Q8 memory calculation](geekom-q8-slot-budget-2026-10-17.md). Flash is unchanged.

These use one physical inference resource and switch exclusively. Two slots are
reserved for interactive coding and enforced by the authenticated owner gateway. Nominal “128k” labels
on the four dense entries mean 122880 actual configured tokens.

## cachyos-mini-mobile · Radeon RX 7900 XT (OCuLink)

The 20 GiB Radeon connects to the laptop through OCuLink. Rootless Podman
runs the pinned ROCm backend; weights and its dedicated container store live on
`/mnt/xfs/AI_Models`. The alias is available when the registered card is connected
and powered at boot. Without it, inference stays stopped; the internal GPU is
never a fallback.

| Model | What to use it for | Context and concurrency |
| --- | --- | --- |
| rdn xt - 128k 3 slots - Muse Glimmer | Agent/tool workloads and coding | Three slots of 131072 tokens; plain model |
| rdn xt - 128k 2 slots - Muse Glimmer DFlash | Compare speculative decoding with plain Muse | Two slots of 131072 tokens; sampled VRAM margin is tight |
| rdn xt - 128k 1 slot - qwen3.8 | Longer Qwen requests on the Radeon | One slot of 131072 tokens; q8 KV on GPU |

The Radeon 256k CPU-KV and all 32k Qwen choices are retired. The retained windows
reuse one Qwen weight file. Smaller windows can reduce primary Hermes eligibility;
`lario-fleet` uses the ready model's real context and slots, not the menu count.
All Hermes agents remain paused until the user explicitly resumes them.

## bigcachy · NVIDIA RTX 5080

The 16 GiB RTX serves one chat/vision profile at a time. Image generation borrows
the idle card for one job and restores the saved chat/vision selection afterwards.

| Model / profile | What to use it for | Context or output |
| --- | --- | --- |
| gfc rtx - 32k 1 slot - qwen3-VL OCR / comparison | Invoice text, screenshots and comparing pictures | One 32768-token slot; higher image-token allowance |
| gfc rtx - 64k 1 slot - qwen3-VL description | Image descriptions and extracted video-frame comparisons | One 65536-token slot; lower per-image token allowance |
| gfc rtx - 64k 1 slot - qwen3.8 | Coding and general text work | One 65536-token slot; validated q4 KV on GPU; the only RTX Qwen window |
| gfc rtx · qwen Image 2.1 Uncensored Q4 | Prompted raster assets and image-generation experiments | Tested at 512 and 1024 pixels; text encoder/image cache offloaded to RAM |
| gfc rtx · FLUX.2-klein-4B | Short-step image iteration and prototyping assets | Distilled four-step workflow; tested at 512 and 1024 pixels; CPU text encoder |

The two vision profiles share one weight file. Image models are MCP/CLI tools,
not chat-provider entries. Video testing used generated frame pairs, not native
full-video quality evaluation. Editing, transparency and UI design quality have
not been scored. Current thermal findings and any incomplete tests are recorded
in the benchmark report; a successful smoke request is not a thermal stability claim.

## bigcachy · Intel CPU, iGPU and NPU

These four services stay resident without a model-switch alias. They use system
RAM and native OpenVINO GenAI. Intel Qwen is for translation only; it is not a
coding model in OpenCode.

| Model | Device | What to use it for |
| --- | --- | --- |
| intel · BAAI BGE-M3 FP16 | CPU | Compatible RAG embeddings and semantic ranking: CLS pooling, L2 normalization, 1024 dimensions, 8192-token input |
| intel · Whisper large-v3-turbo FP16 | NPU | Multilingual speech transcription; original-language text |
| intel · qwen3-8B INT4 | Intel iGPU, GPU.0 | Text translation preserving meaning, numbers and formatting |
| intel · Kokoro-82M INT8 | CPU | Local speech synthesis; English and supported phonemized voices |

The measured device choices and exact software pins are in
[the Intel hardware guide](../intel/README.md). The compatible embedding space
is retained; matching vector dimensions alone would not preserve the RAG database.

## bigcachy · b70 (first profile live)

All B70 targets use Q4-family weights and Q4 K/V, including the Muse draft cache.
Each row below is a mutually exclusive resident choice. **Smart 256k/two slots
is live and allowlisted in OpenCode; the remaining twelve choices are gated.** Existing Intel CPU/iGPU/NPU services remain separate.

| Model name / family | Context and slots | Use and limits |
| --- | --- | --- |
| b70 · qwen3.8 smrt | 128k × 5, 256k × 2, 512k × 1, 640k × 1 | xhigh reasoning; Q4 weights; above-native windows unvalidated |
| b70 · qwen3.8 md | 128k × 5, 256k × 2, 512k × 1, 640k × 1 | Medium reasoning on the same Q4 weights |
| b70 · qwen3.8 smrt / md · RAM KV | 512k × 2 for each reasoning choice | Explicit CPU Q4 cache, 19.125 GiB host cache budget |
| b70 - 256k 12 slots - Muse Glimmer DFlash | 262144 tokens per slot | Calculated capacity; native Muse context is 128k |
| b70 - 512k 6 slots - Muse Glimmer DFlash | 524288 tokens per slot | Extended-context preparation; quality unvalidated |
| b70 - 1696k 2 slots - Muse Glimmer DFlash | 1736704 tokens per slot | Half the one-slot memory ceiling; aggressive 13.25× extension, not a quality guarantee |

All thirteen entries, with enabled status, are visible through read-only MCP discovery with
`model_options({"hardware":"arcB70"})` and in the prepared model-page inventory.
[Memory calculations](arcb70-capacity-2026-10-23.md) include target/draft weights,
bounded sliding caches and an unverified 3.5 GiB reserve. Real hardware/runtime,
allocation and later context quality must pass before enabling additional choices.
The B70 driver reports 31.890625 GiB usable memory; the staged maximum based
on 32 GiB must be recalculated before activation. See the
[first live functional and thermal checks](benchmarks-2026-10-23.md).

## A useful UI workflow

Use Geekom Qwen to plan and implement the interface, RTX OCR to inspect and compare
screenshots, and FLUX or Qwen Image for raster assets. Keep typography, spacing
and components in source code. This is a practical workflow, not a measured claim
that one model is the best UI designer.

## OpenCode and daily operation

| Client | Chat providers | Model/image tools |
| --- | --- | --- |
| bigcachy and l-dev-ai | Geekom, Radeon, RTX | Read-only status/options; lifecycle via model page; image generation through owner access |
| cachyos-mini-mobile | Geekom, Radeon, RTX | Read-only status/options; lifecycle via model page; image choices |
| media (retired client) | Retained configuration only | Read-only model and image choices |
| All configured clients | Intel workload tools | Seven Intel tools; no Intel chat provider |

All model weights and caches on all three inference hosts remain on XFS. Persistent
owner units and saved selections support boot recovery; the remaining physical
cold-start orders are documented separately. MCP discovery survives an offline
host, and subsequent calls reconnect when it returns.

Read [the MCP guide](mcp-guide.md) for prompts, tool arguments and troubleshooting,
[the benchmark report](benchmarks.html) for measured results and limitations,
and [boot instructions](BOOT.md) for startup/recovery checks.

## Removing or repositioning a GPU

Power off and disconnect power before moving either card. On bigcachy’s ASUS
ProArt Z890-CREATOR WIFI, use the two CPU Gen5 slots for the pair: they support
x8/x8. The bottom Gen4 slot is x4 and shares bandwidth with M.2_5. A gap below
the RTX intake may help cooling, provided the case floor or PSU shroud leaves
clearance. See the [board manual](https://dlcdnets.asus.com/pub/ASUS/mb/LGA1851/ProArt_Z890-CREATOR_WIFI/E25472_ProArt_Z890-CREATOR_WIFI_EM_V2_WEB.pdf).

Temporarily removing Radeon makes the `7900xt` chat alias unavailable; it stays
in OpenCode’s configuration and does not automatically route to another GPU.
Geekom, RTX, Intel and RAG do not depend on the Radeon service. Disable the
`xt` Compose startup profile before booting without the card: its required
`/dev/kfd` and Radeon render-node mapping will otherwise prevent the container
from starting. Verify the Radeon PCI/render-node mapping when reinstalling it,
because numbered DRM nodes can change. Keep Hermes paused during hardware work.

## Start and stop inference

Run `7900xt start`, `7900xt stop`, `geekom start`, `geekom stop`,
`rtx5080 start` or `rtx5080 stop` on any configured development machine.
Commands forward to the hardware owner. Starting restores the saved model and
preset; add `--experimental` if that saved profile is still experimental.
Stopping checks occupancy and drains an authenticated gateway before stopping.
A busy or unknown backend is refused; there is no force-cancel option. The operator Off state is durable across reboots; startup respects it until
explicitly turned On again.

The agent-facing `lario_models` MCP is read-only: use `model_status` and
`model_options`. Start/stop, activation and cancellation belong to the
[authenticated model controls](https://models.in.drlario.org). `model_start`,
`model_stop` and mutable alias switching are retired from this MCP.

B70 discovery: `model_options({"hardware":"arcB70"})` lists thirteen prepared
Q4-only profiles. Muse DFlash adds 256k/twelve, 512k/six and 1696k/two slots;
all are unvalidated extensions beyond native 128k, not ready inference capacity.
Names use compact hardware prefixes (`gkm`, `rdn xt`, `gfc rtx`, `intel`, `b70`)
and `qwen`, `smrt`, `md`, with context/slots near the front. See the
[MCP guide](mcp-guide.md) and [B70 budget](arcb70-capacity-2026-10-23.md).

Current migration evidence: [October 17 checks](benchmarks-2026-10-17.md).

## Model monitoring

Open [Local models](https://models.in.drlario.org) for the resident model on each
owner, context/slots, readiness, GPU memory/temperature/utilisation, available RAM
and sanitized request/error logs. It covers Geekom, the mini-mobile 7900 XT, RTX
and the four Intel workloads. The current resident identity comes from the owner
API; an OpenCode dropdown selection alone does not establish backend residency.

[Model logs and Grafana](https://models.logs.in.drlario.org) and
[Prometheus](https://prometheus.in.drlario.org) retain their existing domains.
The collectors run independently of inference and never load or switch models.
The hardware selector filters model logs and metrics. Choose arcB70 for its
separate request/lifecycle events, temperatures, fan RPM and board power.
See [observability operation and validation](../observability/README.md) for
privacy filtering, retention, offline behavior and repair instructions.
