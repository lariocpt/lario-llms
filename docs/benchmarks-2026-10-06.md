# Benchmarks — 2026-10-06

This report consolidates the October 5–6 latency, correctness, context, memory,
image-generation and client checks. Raw results and initial failures remain
linked below. Other host activity was not excluded. Hermes was active during
earlier Geekom tests and paused for the final tests.

> GPU benchmarks now run sequentially. RTX reached 88°C at 99% fans during the
> first final coding run while Radeon load was present. Only the owned RTX
> benchmark was stopped. A hot or incomplete run does not qualify for promotion.

## Requested model configuration

| Hardware | Retained Qwen options | Other workloads |
| --- | --- | --- |
| Radeon RX 7900 XT | One 65536-token or 131072-token slot; GPU q8 KV | Muse Glimmer plain and DFlash |
| NVIDIA RTX 5080 | One 65536-token slot only; GPU q8 KV | Qwen3-VL OCR/description; Qwen Image Q4 and FLUX Klein image tools |
| Geekom Strix Halo | Four dense Qwen entries; Flash large-window/balanced and six-slot 131072 choice | Exclusive primary coding/reasoning host |
| Intel on bigcachy | Qwen3-8B INT4 translation only | Compatible CPU BGE-M3, NPU Whisper and CPU Kokoro |

Removed presets share retained weights, so no still-used file is deleted. Fleet
budgeting uses ready context/slots and reservations, not the number of menu items.
Reservations remain advisory: production authenticated admission is not active.

## Measured performance changes

| Change | Median long-prompt decode | Median first-content time | Interpretation |
| --- | --- | --- | --- |
| Radeon matched 128k q8 CPU → GPU KV | 7.206 → 29.423 tokens/s, 4.08× | 17.544 → 13.551 s | Equal context and Q3 weights; five long/five short repeats each |
| RTX original 262k CPU → 64k GPU KV | 8.31 → 53.63 tokens/s, 6.45× | 8.236 → 5.307 s | Smaller context; not an equal-context speedup |
| Geekom Flash four → three maximum-window slots | 22.36 → 26.88 tokens/s, 1.20× | 30.299 → 24.614 s | Same per-slot context; one fewer concurrent slot |

The fixture labelled latency-8k actually measures 11036 prompt tokens on the
Qwen tokenizer. Outputs are deliberately capped at 256, cache_prompt is false,
and requested reasoning controls are recorded. These small shared-service runs
do not establish isolated p95 latency, latency reservations or general quality.

## Correctness and context

| Profile | Verified scope | Failures and limits retained |
| --- | --- | --- |
| Geekom Flash balanced | Tools and RAG 10/10; ten coding cases across original run plus affected evaluator retest; markers at 237578 input tokens | Concurrent coding timed out at 600 s. Earlier 30-minute telemetry contained batches, not continuous mixed traffic |
| Geekom Flash six-slot 128k | Settled short concurrency 18/18, tools 10/10, latency 6/6; markers at 126986 input tokens | Initial large six-way attempt: five timeouts and one 429. Fifteen-minute shared-load minimum RAM 19.950 GiB; about 1.12 GiB swap-out |
| Radeon Qwen 128k | Earlier coding/tools/RAG all 10/10, near-limit markers; final tools and RAG each 10/10 | Sustained final decision recorded below |
| Radeon Qwen 64k | Five long/five short repeats; final tools/RAG/actual OpenCode coding 10/10 each; markers at 61450 actual input tokens | Quality/context window passed; separate sustained run pending |
| Muse plain and DFlash | Each tools and actual coding 10/10 | At 1024 output tokens, latency final content only 3/10 plain and 0/10 DFlash; effective thinking cap unproven. DFlash margin 0.516 GiB misses the 2 GiB target |
| RTX Qwen 64k | Prior marker check; final tools and RAG each 10/10 | Final coding stopped for heat after nine stored cases: eight passed, flatten failed; tenth interrupted |
| RTX OCR | Both synthetic runs 20/20 | Not a complete document/video quality evaluation |
| RTX description | First strict run 13/20; repeated frame checks 8/8 | Corrected semantic grader retest passed six cases before Xid79/154 and backend abort; not a complete quality score |

Coding uses real OpenCode in disposable directories with behavioral evaluation.
An evaluator fix or affected retest is disclosed rather than rewriting failed
results. RAG suites verify rank, source and supported answers in disposable
BGE-M3 collections, then delete them and verify cleanup. No benchmark fixture
is added to the production KB. Near-limit marker recall is not a broad reasoning
quality score. Full cross-model UI-design quality is untested.

## Image generation

All six files and pinned runtime commits were independently checked. The XFS
runtime uses Python 3.12.13 and Torch 2.14.1+cu130, native sm_120, CPU text encoders
and Qwen CPU image cache. Every real PNG job restored the saved 64k Qwen profile.

| Model / size | Steps | Generation | With restoration | Sampled image VRAM peak |
| --- | --- | --- | --- | --- |
| Qwen Image Q4, 512×512 | 8 | 46.566 s | 58.342 s | 5597 MiB |
| Qwen Image Q4, 1024×1024 | 25 | 46.553 s | 54.353 s | 5853 MiB |
| FLUX Klein, 512×512 | 4 | 14.167 s | 21.797 s | 8077 MiB |
| FLUX Klein, 1024×1024 | 4 | 24.293 s | 30.947 s | 8085 MiB |

All four PNG dimensions/headers/hashes passed; both FLUX jobs used actual MCP
initialize/list/generate. These single seeded cases differ in cache state and
step count, so they are not a quality ranking. FLUX 512 observed 32474 global
swap-out pages; attribution to its job alone is unproven. Editing, alpha output,
detailed lettering and UI-design quality remain unscored.

## Intel device selection

| Small workload | CPU | Intel iGPU | NPU | Selected device |
| --- | --- | --- | --- | --- |
| BGE-M3, four short texts | 0.229 s | 0.213 s | 0.748 s at shorter 512-token geometry | CPU preserves the full 8192-token RAG contract |
| Whisper, 10.435 s English clip | 3.220 s | 2.570 s | 2.019 s | NPU; 73.9 s cold compile separately |
| Qwen3-8B translation sentence | 5.305 s | 1.399 s | Export compile failed | GPU.0 |
| Kokoro, 1.925 s English speech | 0.927 s | 8.025 s | 1.021 s | CPU; NPU compile diagnostics retained |

OpenVINO Runtime/GenAI/tokenizers ABI is pinned to matching 2026.4. CPU/iGPU
BGE-M3 pairwise ranking was preserved with minimum cosine 0.9999999992 /
0.99999179 on four multilingual texts versus the original encoder. NPU's shorter
embedding window violates the RAG contract. Measurements justify these tested
device choices, not best-in-class multilingual accuracy. Details and software
pins are in [the Intel guide](../intel/README.md).

## OpenCode and client checks

Actual bigcachy OpenCode model-options/status calls passed in 163.041 s and
image-options in 13.198 s, with unchanged background PID and no model switch.
Media's seven Intel tools and real ranking passed, but it has no OpenCode CLI.

Mini-mobile's five repos were safely fast-forwarded; its older LLM branch was
preserved and the clean checkout switched to main. machine-setup PR12/f9d92e1
retired its stale llamaswap/main default-agent override and duplicate provider,
and fixed Geekom's matching local/main override. Mini's actual global and default
agent now use geekom/geekom. OpenCode 1.18.21 connected all three MCPs and returned
MINI_OPENCODE_OK in 90.983 s. Consumer key files are private 0600, with no backend
or management keys exported. Connection alone is not actual tool-use proof.

## NVIDIA heat and test policy

At 16:41 SAST the RTX reported 88°C, 319.75 W, 99% fans, 96% utilization and zero
maximum-operating margin. Current power limit was 380 W versus the board's 360 W
default. Thermal slowdown counters were nonzero; their instantaneous flags were
inactive at the snapshot. Only the owned RTX coding benchmark was stopped;
user OpenCode and model services stayed running. Temperature fell to 71°C,
then 51°C while Radeon continued. The user confirmed Radeon sits directly below RTX.

Radeon exhaust recirculation is plausible from the layout, but intake temperature
and paired airflow measurements are unavailable. These later readings do not
establish the earlier Xid79 cause; no memory-junction reading was available.
NVIDIA lists an 88°C reference maximum in its [RTX specifications](https://www.nvidia.com/en-au/geforce/graphics-cards/50-series/rtx-5080/).
Its [Xid reference](https://docs.nvidia.com/deploy/pdf/XID_Errors.pdf) describes
Xid79 as PCIe GPU-access loss, often associated with link hardware failure.
Host evidence: [thermal readings](../research/rtx-thermal-check-20261006.json)
and [original incident](../research/rtx-driver-incident-20261006.json).

The user reports a dual-width RTX above a single-width Radeon with no gap;
reversing them would leave a gap. The identified ASUS ProArt Z890-CREATOR WIFI
has two CPU Gen5 slots supporting x8/x8. Both current root links report x8;
the Radeon endpoint behind its bridge reports x16, which does not mean a
16-lane CPU connection. Swapping these two Gen5 positions should preserve lane
allocation while potentially improving intake clearance. The bottom Gen4 slot
is only x4 and is disabled when M.2_5 operates. See the
[ASUS manual](https://dlcdnets.asus.com/pub/ASUS/mb/LGA1851/ProArt_Z890-CREATOR_WIFI/E25472_ProArt_Z890-CREATOR_WIFI_EM_V2_WEB.pdf).
No physical change or fan/power adjustment has been performed.

Tests now run sequentially on individual GPUs. The sustained RTX runner stops
launching requests at 84°C and records the event; fan/power settings are unchanged.
The mixed runner uses short, 11k-input and two-step tool requests with scoped
RAM/VRAM/PSI/swap telemetry, paired with separate coding/RAG/context checks.

## Final retained-profile decisions

Radeon 128k passed 166/166 sustained requests over 1814.745 seconds. Minimum free
Radeon VRAM was 2.7149 GiB, minimum available host RAM 90.4895 GiB, maximum memory
PSI full avg10 was 0%, and swap-out was 25 pages (about 100 KiB), with no repeated
pressure. Together with five-repeat matched latency, ten coding/tool/RAG checks
and near-limit marker recall, this retained profile is validated and no longer
labelled experimental. This is a scoped model decision, not production admission.

Radeon 64k final tools, RAG and actual OpenCode coding each passed 10/10; its
near-limit test recovered all markers at 61450 actual input tokens. The scoped
quality/context telemetry covered 705.7 seconds, with minimum free
Radeon VRAM 5.0672 GiB, minimum available RAM
93.2277 GiB and zero swap-out pages. Radeon maxima were
56°C edge, 93°C junction and 89°C memory. RTX stayed idle
and never exceeded 49°C. This is not its separate 30-minute sustained gate,
so the 64k experimental label remains. Further GPU load is held while the user
considers rearranging or temporarily removing Radeon. Other retained profile
decisions remain pending relevant quality, headroom and thermal checks.
Physical l-dev-ai-only and both-powered-off boot orders still require manual power
coordination; authenticated production admission remains a separate gate.

## Raw result index

Stored-row totals do not make an interrupted suite complete. Every initial
failure, retest and telemetry artifact is retained below.

<!-- BEGIN GENERATED RESULT INDEX -->
| Artifact | Scope | Stored result |
| --- | --- | --- |
| [api-smoke](../intel/research/api-smoke.json) | runtime / device checks | see artifact |
| [asr-CPU](../intel/research/asr-CPU.json) | /mnt/xfs/AI_Models/openvino/asr/whisper-large-v3-turbo-fp16 | see artifact |
| [asr-GPU](../intel/research/asr-GPU.json) | /mnt/xfs/AI_Models/openvino/asr/whisper-large-v3-turbo-fp16 | see artifact |
| [asr-NPU-fixed](../intel/research/asr-NPU-fixed.json) | /mnt/xfs/AI_Models/openvino/asr/whisper-large-v3-turbo-fp16 | see artifact |
| [asr-NPU](../intel/research/asr-NPU.json) | /mnt/xfs/AI_Models/openvino/asr/whisper-large-v3-turbo-fp16 | see artifact |
| [embedding-CPU](../intel/research/embedding-CPU.json) | /mnt/xfs/AI_Models/openvino/embeddings/bge-m3-fp16 | see artifact |
| [embedding-GPU](../intel/research/embedding-GPU.json) | /mnt/xfs/AI_Models/openvino/embeddings/bge-m3-fp16 | see artifact |
| [embedding-NPU-fixed](../intel/research/embedding-NPU-fixed.json) | /mnt/xfs/AI_Models/openvino/embeddings/bge-m3-fp16 | see artifact |
| [embedding-NPU](../intel/research/embedding-NPU.json) | /mnt/xfs/AI_Models/openvino/embeddings/bge-m3-fp16 | see artifact |
| [embedding-compatibility](../intel/research/embedding-compatibility.json) | runtime / device checks | see artifact |
| [npu-smoke-with-compiler](../intel/research/npu-smoke-with-compiler.json) | runtime / device checks | see artifact |
| [npu-smoke](../intel/research/npu-smoke.json) | runtime / device checks | see artifact |
| [translation-CPU-fixed](../intel/research/translation-CPU-fixed.json) | /mnt/xfs/AI_Models/openvino/translation/qwen3-8b-int4 | see artifact |
| [translation-CPU](../intel/research/translation-CPU.json) | /mnt/xfs/AI_Models/openvino/translation/qwen3-8b-int4 | see artifact |
| [translation-GPU-fixed](../intel/research/translation-GPU-fixed.json) | /mnt/xfs/AI_Models/openvino/translation/qwen3-8b-int4 | see artifact |
| [translation-GPU](../intel/research/translation-GPU.json) | /mnt/xfs/AI_Models/openvino/translation/qwen3-8b-int4 | see artifact |
| [translation-NPU](../intel/research/translation-NPU.json) | /mnt/xfs/AI_Models/openvino/translation/qwen3-8b-int4 | see artifact |
| [tts-CPU-fixed](../intel/research/tts-CPU-fixed.json) | /mnt/xfs/AI_Models/openvino/tts/kokoro-82m-int8 | see artifact |
| [tts-CPU](../intel/research/tts-CPU.json) | /mnt/xfs/AI_Models/openvino/tts/kokoro-82m-int8 | see artifact |
| [tts-GPU](../intel/research/tts-GPU.json) | /mnt/xfs/AI_Models/openvino/tts/kokoro-82m-int8 | see artifact |
| [tts-NPU](../intel/research/tts-NPU.json) | /mnt/xfs/AI_Models/openvino/tts/kokoro-82m-int8 | see artifact |
| [tts-portuguese-api](../intel/research/tts-portuguese-api.json) | kokoro-82m-int8 | see artifact |
| [20261005-bigcachy-memory](../research/benchmarks/20261005-bigcachy-memory.json) | telemetry | 11 samples |
| [20261005-geekom-admission-shadow-canary](../research/benchmarks/20261005-geekom-admission-shadow-canary.json) | runtime / device checks | PASS |
| [20261005-geekom-balanced-baseline](../research/benchmarks/20261005-geekom-balanced-baseline.json) | runtime / device checks | 10/10 stored rows passed |
| [20261005-geekom-balanced-concurrency3-initial](../research/benchmarks/20261005-geekom-balanced-concurrency3-initial.json) | runtime / device checks | 29/30 stored rows passed |
| [20261005-geekom-balanced-concurrency3-short-retest](../research/benchmarks/20261005-geekom-balanced-concurrency3-short-retest.json) | runtime / device checks | 15/15 stored rows passed |
| [20261005-geekom-balanced-memory](../research/benchmarks/20261005-geekom-balanced-memory.json) | telemetry | 31 samples |
| [20261005-geekom-balanced-mixed-memory](../research/benchmarks/20261005-geekom-balanced-mixed-memory.json) | telemetry | 361 samples |
| [20261005-geekom-balanced-tools](../research/benchmarks/20261005-geekom-balanced-tools.json) | tools | 10/10 stored rows passed |
| [20261005-geekom-capacity-baseline](../research/benchmarks/20261005-geekom-capacity-baseline.json) | runtime / device checks | 10/10 stored rows passed |
| [20261005-geekom-held-telemetry](../research/benchmarks/20261005-geekom-held-telemetry.json) | telemetry | 11 samples |
| [20261005-opencode-health](../research/benchmarks/20261005-opencode-health.json) | runtime / device checks | PASS |
| [20261005-rtx-capacity-baseline](../research/benchmarks/20261005-rtx-capacity-baseline.json) | runtime / device checks | 10/10 stored rows passed |
| [20261005-rtx-capacity-coding-pilot](../research/benchmarks/20261005-rtx-capacity-coding-pilot.json) | coding | 0/1 stored rows passed |
| [20261005-rtx-capacity-tools](../research/benchmarks/20261005-rtx-capacity-tools.json) | tools | 10/10 stored rows passed |
| [20261005-rtx-fast128-startup](../research/benchmarks/20261005-rtx-fast128-startup.json) | qwen3.8 | FAIL |
| [20261005-rtx-fast32-baseline](../research/benchmarks/20261005-rtx-fast32-baseline.json) | runtime / device checks | 10/10 stored rows passed |
| [20261005-rtx-fast32-coding-frequency-retest](../research/benchmarks/20261005-rtx-fast32-coding-frequency-retest.json) | coding | 1/1 stored rows passed |
| [20261005-rtx-fast32-coding-full-initial](../research/benchmarks/20261005-rtx-fast32-coding-full-initial.json) | coding | 9/10 stored rows passed |
| [20261005-rtx-fast32-coding-pilot](../research/benchmarks/20261005-rtx-fast32-coding-pilot.json) | coding | 0/1 stored rows passed |
| [20261005-rtx-fast32-coding-scoped](../research/benchmarks/20261005-rtx-fast32-coding-scoped.json) | coding | 0/1 stored rows passed |
| [20261005-rtx-fast32-coding-verified](../research/benchmarks/20261005-rtx-fast32-coding-verified.json) | coding | 1/1 stored rows passed |
| [20261005-rtx-fast32-long](../research/benchmarks/20261005-rtx-fast32-long.json) | long | 1/1 stored rows passed |
| [20261005-rtx-fast32-memory](../research/benchmarks/20261005-rtx-fast32-memory.json) | telemetry | 11 samples |
| [20261005-rtx-fast32-rag-isolated](../research/benchmarks/20261005-rtx-fast32-rag-isolated.json) | rag | 10/10 stored rows passed |
| [20261005-rtx-fast32-rag-retest](../research/benchmarks/20261005-rtx-fast32-rag-retest.json) | rag | 0/1 stored rows passed |
| [20261005-rtx-fast32-rag](../research/benchmarks/20261005-rtx-fast32-rag.json) | rag | 0/1 stored rows passed |
| [20261005-rtx-fast32-tools](../research/benchmarks/20261005-rtx-fast32-tools.json) | tools | 10/10 stored rows passed |
| [20261005-rtx-fast64-baseline](../research/benchmarks/20261005-rtx-fast64-baseline.json) | runtime / device checks | 10/10 stored rows passed |
| [20261005-rtx-fast64-long-memory](../research/benchmarks/20261005-rtx-fast64-long-memory.json) | telemetry | 118 samples |
| [20261005-rtx-fast64-long](../research/benchmarks/20261005-rtx-fast64-long.json) | long | 1/1 stored rows passed |
| [20261006-7900-admission-shadow-canary](../research/benchmarks/20261006-7900-admission-shadow-canary.json) | runtime / device checks | PASS |
| [20261006-7900-capacity-latency](../research/benchmarks/20261006-7900-capacity-latency.json) | runtime / device checks | 10/10 stored rows passed |
| [20261006-7900-capacity-long](../research/benchmarks/20261006-7900-capacity-long.json) | long | 1/1 stored rows passed |
| [20261006-7900-capacity-memory](../research/benchmarks/20261006-7900-capacity-memory.json) | telemetry | 73 samples |
| [20261006-7900-capacity-rag](../research/benchmarks/20261006-7900-capacity-rag.json) | rag | 10/10 stored rows passed |
| [20261006-7900-capacity-tools](../research/benchmarks/20261006-7900-capacity-tools.json) | tools | 10/10 stored rows passed |
| [20261006-7900-cpu128-latency](../research/benchmarks/20261006-7900-cpu128-latency.json) | runtime / device checks | 10/10 stored rows passed |
| [20261006-7900-cpu32-latency](../research/benchmarks/20261006-7900-cpu32-latency.json) | runtime / device checks | 10/10 stored rows passed |
| [20261006-7900-cpu32-memory](../research/benchmarks/20261006-7900-cpu32-memory.json) | telemetry | 91 samples |
| [20261006-7900-cpu32-tools](../research/benchmarks/20261006-7900-cpu32-tools.json) | tools | 10/10 stored rows passed |
| [20261006-7900-dflash-coding](../research/benchmarks/20261006-7900-dflash-coding.json) | coding | 10/10 stored rows passed |
| [20261006-7900-dflash-latency](../research/benchmarks/20261006-7900-dflash-latency.json) | runtime / device checks | 0/10 stored rows passed |
| [20261006-7900-dflash-memory](../research/benchmarks/20261006-7900-dflash-memory.json) | muse-glimmer-dflash | see artifact |
| [20261006-7900-dflash-tools](../research/benchmarks/20261006-7900-dflash-tools.json) | tools | 10/10 stored rows passed |
| [20261006-7900-fast128-coding](../research/benchmarks/20261006-7900-fast128-coding.json) | coding | 10/10 stored rows passed |
| [20261006-7900-fast128-final-rag](../research/benchmarks/20261006-7900-fast128-final-rag.json) | rag | 10/10 stored rows passed |
| [20261006-7900-fast128-final-tools](../research/benchmarks/20261006-7900-fast128-final-tools.json) | tools | 10/10 stored rows passed |
| [20261006-7900-fast128-latency](../research/benchmarks/20261006-7900-fast128-latency.json) | runtime / device checks | 10/10 stored rows passed |
| [20261006-7900-fast128-long](../research/benchmarks/20261006-7900-fast128-long.json) | long | 1/1 stored rows passed |
| [20261006-7900-fast128-memory](../research/benchmarks/20261006-7900-fast128-memory.json) | qwen3.8 | see artifact |
| [20261006-7900-fast128-mixed30](../research/benchmarks/20261006-7900-fast128-mixed30.json) | sustained-mixed | 166/166 stored rows passed |
| [20261006-7900-fast128-rag](../research/benchmarks/20261006-7900-fast128-rag.json) | rag | 10/10 stored rows passed |
| [20261006-7900-fast128-tools](../research/benchmarks/20261006-7900-fast128-tools.json) | tools | 10/10 stored rows passed |
| [20261006-7900-fast32-latency](../research/benchmarks/20261006-7900-fast32-latency.json) | runtime / device checks | 10/10 stored rows passed |
| [20261006-7900-fast32-memory](../research/benchmarks/20261006-7900-fast32-memory.json) | telemetry | 119 samples |
| [20261006-7900-fast32-tools](../research/benchmarks/20261006-7900-fast32-tools.json) | tools | 10/10 stored rows passed |
| [20261006-7900-fast64-final-coding](../research/benchmarks/20261006-7900-fast64-final-coding.json) | coding | 10/10 stored rows passed |
| [20261006-7900-fast64-final-long](../research/benchmarks/20261006-7900-fast64-final-long.json) | long | 1/1 stored rows passed |
| [20261006-7900-fast64-final-memory](../research/benchmarks/20261006-7900-fast64-final-memory.json) | telemetry | 141 samples |
| [20261006-7900-fast64-final-rag](../research/benchmarks/20261006-7900-fast64-final-rag.json) | rag | 10/10 stored rows passed |
| [20261006-7900-fast64-final-tools](../research/benchmarks/20261006-7900-fast64-final-tools.json) | tools | 10/10 stored rows passed |
| [20261006-7900-fast64-latency](../research/benchmarks/20261006-7900-fast64-latency.json) | runtime / device checks | 10/10 stored rows passed |
| [20261006-7900-fast64-long](../research/benchmarks/20261006-7900-fast64-long.json) | long | 1/1 stored rows passed |
| [20261006-7900-fast64-memory](../research/benchmarks/20261006-7900-fast64-memory.json) | telemetry | 177 samples |
| [20261006-7900-muse-coding](../research/benchmarks/20261006-7900-muse-coding.json) | coding | 10/10 stored rows passed |
| [20261006-7900-muse-latency-truncated256-controls](../research/benchmarks/20261006-7900-muse-latency-truncated256-controls.json) | runtime / device checks | 4/10 stored rows passed |
| [20261006-7900-muse-latency-truncated256](../research/benchmarks/20261006-7900-muse-latency-truncated256.json) | runtime / device checks | 0/10 stored rows passed |
| [20261006-7900-muse-latency](../research/benchmarks/20261006-7900-muse-latency.json) | runtime / device checks | 3/10 stored rows passed |
| [20261006-7900-muse-memory](../research/benchmarks/20261006-7900-muse-memory.json) | muse-glimmer | see artifact |
| [20261006-7900-muse-reasoning-diagnostic](../research/benchmarks/20261006-7900-muse-reasoning-diagnostic.json) | muse-glimmer | see artifact |
| [20261006-7900-muse-tools](../research/benchmarks/20261006-7900-muse-tools.json) | tools | 10/10 stored rows passed |
| [20261006-flux-klein-1024-mcp](../research/benchmarks/20261006-flux-klein-1024-mcp.json) | flux-klein | PASS |
| [20261006-flux-klein-512-mcp](../research/benchmarks/20261006-flux-klein-512-mcp.json) | flux-klein | PASS |
| [20261006-geekom-balanced-coding-binary-retest](../research/benchmarks/20261006-geekom-balanced-coding-binary-retest.json) | coding | 1/1 stored rows passed |
| [20261006-geekom-balanced-coding-initial](../research/benchmarks/20261006-geekom-balanced-coding-initial.json) | coding | 9/10 stored rows passed |
| [20261006-geekom-balanced-long-max](../research/benchmarks/20261006-geekom-balanced-long-max.json) | long | 1/1 stored rows passed |
| [20261006-geekom-balanced-long](../research/benchmarks/20261006-geekom-balanced-long.json) | long | 1/1 stored rows passed |
| [20261006-geekom-balanced-rag](../research/benchmarks/20261006-geekom-balanced-rag.json) | rag | 10/10 stored rows passed |
| [20261006-geekom-flash128-concurrency6-short](../research/benchmarks/20261006-geekom-flash128-concurrency6-short.json) | runtime / device checks | 18/18 stored rows passed |
| [20261006-geekom-flash128-concurrency6](../research/benchmarks/20261006-geekom-flash128-concurrency6.json) | runtime / device checks | 0/6 stored rows passed |
| [20261006-geekom-flash128-final-restore](../research/benchmarks/20261006-geekom-flash128-final-restore.json) | runtime / device checks | see artifact |
| [20261006-geekom-flash128-latency](../research/benchmarks/20261006-geekom-flash128-latency.json) | runtime / device checks | 6/6 stored rows passed |
| [20261006-geekom-flash128-long](../research/benchmarks/20261006-geekom-flash128-long.json) | long | 1/1 stored rows passed |
| [20261006-geekom-flash128-memory](../research/benchmarks/20261006-geekom-flash128-memory.json) | telemetry | 201 samples |
| [20261006-geekom-flash128-retest-memory](../research/benchmarks/20261006-geekom-flash128-retest-memory.json) | telemetry | 181 samples |
| [20261006-geekom-flash128-retest-summary](../research/benchmarks/20261006-geekom-flash128-retest-summary.json) | runtime / device checks | see artifact |
| [20261006-geekom-flash128-startup](../research/benchmarks/20261006-geekom-flash128-startup.json) | runtime / device checks | see artifact |
| [20261006-geekom-flash128-summary](../research/benchmarks/20261006-geekom-flash128-summary.json) | runtime / device checks | see artifact |
| [20261006-geekom-flash128-tools](../research/benchmarks/20261006-geekom-flash128-tools.json) | tools | 10/10 stored rows passed |
| [20261006-geekom-mixed-coding-initial](../research/benchmarks/20261006-geekom-mixed-coding-initial.json) | coding | 0/1 stored rows passed |
| [20261006-mini-opencode-default](../research/benchmarks/20261006-mini-opencode-default.json) | runtime / device checks | exit 0; see assertions |
| [20261006-opencode-private-config](../research/benchmarks/20261006-opencode-private-config.json) | qwen3.8 | PASS |
| [20261006-qwen-image-q4-1024](../research/benchmarks/20261006-qwen-image-q4-1024.json) | qwen-image | PASS |
| [20261006-qwen-image-q4-512](../research/benchmarks/20261006-qwen-image-q4-512.json) | qwen-image | PASS |
| [20261006-retained-qwen-sequence](../research/benchmarks/20261006-retained-qwen-sequence.json) | runtime / device checks | see artifact |
| [20261006-rtx-admission-shadow-canary](../research/benchmarks/20261006-rtx-admission-shadow-canary.json) | runtime / device checks | PASS |
| [20261006-rtx-describe-vision-semantic](../research/benchmarks/20261006-rtx-describe-vision-semantic.json) | runtime / device checks | 6/20 stored rows passed |
| [20261006-rtx-describe-vision](../research/benchmarks/20261006-rtx-describe-vision.json) | runtime / device checks | 13/20 stored rows passed |
| [20261006-rtx-fast64-final-coding](../research/benchmarks/20261006-rtx-fast64-final-coding.json) | coding | 8/9 stored rows passed |
| [20261006-rtx-fast64-final-rag](../research/benchmarks/20261006-rtx-fast64-final-rag.json) | rag | 10/10 stored rows passed |
| [20261006-rtx-fast64-final-tools](../research/benchmarks/20261006-rtx-fast64-final-tools.json) | tools | 10/10 stored rows passed |
| [20261006-rtx-ocr-vision-semantic](../research/benchmarks/20261006-rtx-ocr-vision-semantic.json) | runtime / device checks | 20/20 stored rows passed |
| [20261006-rtx-ocr-vision](../research/benchmarks/20261006-rtx-ocr-vision.json) | runtime / device checks | 20/20 stored rows passed |
<!-- END GENERATED RESULT INDEX -->
