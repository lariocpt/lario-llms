# Your local AI fleet

Choose a model by the task you want to do. OpenCode defaults to the Geekom alias;
the aliases follow the model selected on each hardware owner. The picker labels
are static: ask the model-status MCP for current residency and context.

## l-dev-ai · Geekom Strix Halo

The large shared-memory host is the primary coding and reasoning server. All
weights and download caches live on its XFS model partition.

| Model | What to use it for | Context and concurrency |
| --- | --- | --- |
| Qwen3.8 Smart, Q8 | Coding, harder reasoning, planning and reviewing code | 245760 tokens per slot; four capacity slots or three balanced slots |
| Qwen3.8 Smart 128k, Q8 | The same weights with more concurrent shorter requests | 122880 tokens per slot; eight capacity slots or four balanced slots |
| Qwen3.8 Medium, Q4 | Coding and general assistance with less weight memory | 245760 tokens per slot; four capacity slots or three balanced slots |
| Qwen3.8 Medium 128k, Q4 | More concurrent requests using the medium quantization | 122880 tokens per slot; eight capacity slots or four balanced slots |
| Qwen3.8 Flash Next, Q3 | Coding, tools and general work; measured on the large host | 245760 tokens per slot: four capacity or three balanced slots; a separate six-slot 131072-token choice |

These use one physical inference resource and switch exclusively. Two slots are
reserved in the fleet budget for interactive coding. Reservations are currently
advisory; the production admission gateway is not active. Nominal “128k” labels
on the four dense entries mean 122880 actual configured tokens.

## bigcachy · Radeon RX 7900 XT

The 20 GiB Radeon provides the fleet/agent model and an alternative Qwen coding
endpoint. All three models share one card through an exclusive switch group.

| Model | What to use it for | Context and concurrency |
| --- | --- | --- |
| Muse Glimmer Q4 | Agent/tool workloads and coding | Three slots of 131072 tokens; plain model |
| Muse Glimmer Q4 + DFlash | Compare speculative decoding with plain Muse | Two slots of 131072 tokens; sampled VRAM margin is tight |
| Qwen3.8 Q3, 64k | Coding and tool requests that fit the smaller window | One slot of 65536 tokens; q8 KV on GPU |
| Qwen3.8 Q3, 128k | Longer Qwen requests on the Radeon | One slot of 131072 tokens; q8 KV on GPU |

The Radeon 256k CPU-KV and all 32k Qwen choices are retired. The retained windows
reuse one Qwen weight file. Smaller windows can reduce primary Hermes eligibility;
`lario-fleet` uses the ready model's real context and slots, not the menu count.
All Hermes agents remain paused until the user explicitly resumes them.

## bigcachy · NVIDIA RTX 5080

The 16 GiB RTX serves one chat/vision profile at a time. Image generation borrows
the idle card for one job and restores the saved chat/vision selection afterwards.

| Model / profile | What to use it for | Context or output |
| --- | --- | --- |
| Qwen3-VL-8B Q4 · OCR | Invoice text, screenshots and comparing pictures | One 32768-token slot; higher image-token allowance |
| Qwen3-VL-8B Q4 · Describe | Image descriptions and extracted video-frame comparisons | One 65536-token slot; lower per-image token allowance |
| Qwen3.8 Q3 · 64k | Coding and general text work | One 65536-token slot; q8 KV on GPU; the only RTX Qwen window |
| Qwen Image 2.1 Uncensored Q4 | Prompted raster assets and image-generation experiments | Tested at 512 and 1024 pixels; text encoder/image cache offloaded to RAM |
| FLUX.2-klein-4B | Short-step image iteration and prototyping assets | Distilled four-step workflow; tested at 512 and 1024 pixels; CPU text encoder |

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
| BAAI BGE-M3 FP16 | CPU | Compatible RAG embeddings and semantic ranking: CLS pooling, L2 normalization, 1024 dimensions, 8192-token input |
| Whisper large-v3-turbo FP16 | NPU | Multilingual speech transcription; original-language text |
| Qwen3-8B INT4 | Intel iGPU, GPU.0 | Text translation preserving meaning, numbers and formatting |
| Kokoro-82M INT8 | CPU | Local speech synthesis; English and supported phonemized voices |

The measured device choices and exact software pins are in
[the Intel hardware guide](../intel/README.md). The compatible embedding space
is retained; matching vector dimensions alone would not preserve the RAG database.

## A useful UI workflow

Use Geekom Qwen to plan and implement the interface, RTX OCR to inspect and compare
screenshots, and FLUX or Qwen Image for raster assets. Keep typography, spacing
and components in source code. This is a practical workflow, not a measured claim
that one model is the best UI designer.

## OpenCode and daily operation

| Client | Chat providers | Model/image tools |
| --- | --- | --- |
| bigcachy and l-dev-ai | Geekom, Radeon, RTX | Status/options plus guarded switching and image generation through existing owner access |
| cachyos-mini-mobile and media | Geekom, Radeon, RTX | Status/options and image choices; no model-switch or image-generate tool |
| All four clients | Intel workload tools | Seven Intel tools; no Intel chat provider |

All model weights and caches on the two inference hosts remain on XFS. Persistent
owner units and saved selections support boot recovery; the remaining physical
cold-start orders are documented separately. MCP discovery survives an offline
host, and subsequent calls reconnect when it returns.

Read [the MCP guide](mcp-guide.md) for prompts, tool arguments and troubleshooting,
[the benchmark report](benchmarks-2026-10-06.md) for measured results and limitations,
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
