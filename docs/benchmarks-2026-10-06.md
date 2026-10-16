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
| NVIDIA RTX 5080 | One 65536-token slot only; validated GPU q4 KV | Qwen3-VL OCR/description; Qwen Image Q4 and FLUX Klein image tools |
| Geekom Strix Halo | Four dense Qwen entries; Flash large-window/balanced and six-slot 131072 choice | Exclusive primary coding/reasoning host |
| Intel on bigcachy | Qwen3-8B INT4 translation only | Compatible CPU BGE-M3, NPU Whisper and CPU Kokoro |

Removed presets share retained weights, so no still-used file is deleted. Fleet
budgeting uses ready context/slots and reservations, not the number of menu items.
RTX authenticated admission is active and verified. Geekom reservations remain
advisory pending its rollout; removed Radeon has no available capacity.

## October 6 completion checks

The actual bigcachy OpenCode 2 API sees all five qualified model entries with
correct limits after a supported reload; server PID 47013 stayed unchanged.
Actual private configurations were also rendered on Geekom, Mini-mobile and
media, all at mode 0600. Each remote client's configured stdio MCP servers
passed initialize/list: seven Intel tools everywhere, guarded switching and
image generation only on owner-capable clients.

All four machine-setup dry runs and repository syntax checks passed. The current
model/admission regression suite passes 109 tests. Desktop and mobile HTML
readability were visually checked in Chromium with GPU rendering disabled. Portainer 2.39.5 returns HTTP
200 with server 1/1 and agents 2/2. Fresh model-directory audits on both owners
found zero unused candidates; Radeon weights remain protected for deferred reuse.

Evidence: [OpenCode live reload](../research/opencode-live-profile-reload-20261006.json),
[remote client deployment](../research/opencode-client-profile-deployment-20261006.json),
[MCP discovery](../research/client-mcp-discovery-20261006.json),
[Portainer](../research/portainer-health-20261006.json),
[Geekom audit](../research/geekom-cleanup-audit-20261006.json),
[bigcachy audit](../research/bigcachy-cleanup-audit-20261006.json).
RTX backend profile inference and its sustained gates subsequently passed below;
Geekom's fresh sequential checks are in progress.

## RTX isolated baseline after Radeon removal

The all-GPU 64k q8 profile passed **346/346** mixed requests over **1806.656 s**.
Peak sampled temperature was **74°C**, with no thermal stop, no current-boot
NVIDIA fault markers and zero swap-out. Minimum available host RAM was
97.488 GiB. Minimum free VRAM was **1.520 GiB**, just above the agreed RTX minimum of
1.5 GiB (Radeon requires 2 GiB). More margin is desirable, but this success
does not by itself complete the remaining quality gates.

Matched 64k q8 CPU/GPU KV comparisons passed ten responses each: median long
decode was 10.845 versus 53.753 tokens/s, with TTFT 7.680 versus 5.282 seconds.
A three-layer RAM-offload candidate produced 23.328 tokens/s and 1.945 GiB
minimum free VRAM. Its later sustained run was cancelled after these measurements:
the small margin gain does not justify halving decode speed. Its completed
quality results and interrupted work remain in the raw evidence. A supported
q4 KV candidate subsequently passed with more headroom and retained decode speed.
The original overlapping test reached 88°C; the different load
and removed card prevent attributing the temperature difference solely to airflow.
[Raw sustained result](../research/benchmarks/20261006-rtx-fast64-solo-mixed30.json)
and [current-boot fault check](../research/rtx-solo-kernel-check-20261006.json).

## RTX q4 KV — validated and selected

All-GPU q4 KV at the same 64k window completed ten latency responses, tools
10/10, RAG 10/10 with cleanup, and near-limit marker recall. Its initial median
long decode was **53.608 tokens/s**, versus q8's 53.753; TTFT was **5.251 s**
versus 5.282. Minimum free VRAM during that latency window rose from
**1.516 to 2.516 GiB**, with a 69-degree sampled peak. Actual OpenCode coding
passed **10/10**, including the earlier failed flatten case. Near-limit recall
passed at **61450 actual prompt tokens**.

The sustained run passed **344/344** requests over **1802.907 seconds**,
with **2.510 GiB** minimum free VRAM, **97.355 GiB** minimum available host RAM,
**73°C** maximum temperature and **zero swap-in/out pages**. This preserves
decode speed while gaining roughly 1 GiB of VRAM margin. The 64k q4 profile is
selected and no longer experimental; OCR/description retain their q8 caches.

The installed CUDA build is 11392/46847e615 with native sm_120 and q4/q4 flash
attention compiled. A [historical upstream Blackwell q4 issue](https://github.com/ggml-org/llama.cpp/issues/23693)
was reported against an older build and is closed; this alone does not establish
correctness on our model. The current candidate is judged by its actual quality
and context results.

The corrected description grader passed **100/100** cases: twelve synthetic
invoice fixtures and eight frame comparisons, five repeats each. Peak sampled
temperature was **71°C**, minimum free VRAM **4.473 GiB**. The saved Qwen profile
was restored. These fixtures do not score arbitrary documents or native videos.

RTX production admission then passed unknown-key rejection, management-role
refusal, nonresident-model conflict, private proxy/child authentication, both
loopback listener checks, shared public/Docker auxiliary-slot overflow and
disconnect recovery without a model restart. A fresh actual OpenCode flatten
case passed through the activated public gateway. Geekom and media completed
RTX requests using their actual rendered provider keys and could not reach its
private backend. The peer reader first assumed JSON rather than JSONC; that
harness preflight failure is retained separately and made no model request.

Evidence: [sustained q4](../research/benchmarks/20261006-rtx-solo-q4-mixed30.json),
[description](../research/benchmarks/20261006-rtx-solo-description-vision.json),
[live admission](../research/benchmarks/20261006-rtx-production-admission.json),
[OpenCode](../research/benchmarks/20261006-rtx-production-opencode-coding.json),
[Geekom client](../research/benchmarks/20261006-rtx-geekom-client.json),
[media client](../research/benchmarks/20261006-rtx-media-client.json).

## Fresh Geekom balanced qualification

A guarded reload retained the existing q8 KV and loading mode. Available RAM
rose from 12.547 to 23.012 GiB; swap used fell from 8.916 to 0.982 GiB. This
observation does not establish a leak. Fresh latency passed 10/10 single
requests and 12/12 three-way requests, with at least 21.902 GiB available and
zero swap-out. Single long decode was 26.967 tokens/s, with 23.927-second TTFT.

Near-limit three-position recall passed at **237578 actual input tokens**, with
855.158-second first-content time, at least 22.306 GiB available and zero
swap-out. Fresh two-step tools and RAG each passed **10/10**, with at least
21.643 GiB available and zero swap-out. Coding and continuous traffic gates are
still running; these partial results do not promote either Flash preset.

Evidence: [near-limit context](../research/benchmarks/20261006-geekom-fresh-long.json),
[quality sequence](../research/benchmarks/20261006-geekom-fresh-final-quality-sequence.json),
[tools](../research/benchmarks/20261006-geekom-fresh-tools.json),
[RAG](../research/benchmarks/20261006-geekom-fresh-rag.json).

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
| RTX Qwen 64k | q4 coding/tools/RAG 10/10 each; markers at 61450 tokens; sustained 344/344 | Validated; prior heat interruption and failed flatten case retained as history |
| RTX OCR | Both synthetic runs 20/20 | Not a complete document/video quality evaluation |
| RTX description | Corrected semantic grader 100/100, five repeats per fixture | Validated on synthetic invoices/frame pairs; original failed/incomplete runs retained |

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
so the 64k experimental label remains. The user subsequently removed Radeon. It is absent from local PCI inventory,
and RTX now reports x16. The user manually disabled the Radeon restart policy,
stopped its container and cleared the xt boot profile; the empty profile was
read back. Further Radeon tests are deferred. Solo RTX and Geekom tests await
execution-review availability. Other profile decisions remain pending relevant
quality, headroom and thermal checks.
Physical l-dev-ai-only and both-powered-off boot orders still require manual power
coordination; authenticated production admission remains a separate gate.

## Latest source checks and deployment status

The first configuration/docs batch passed the full 83-test suite and was
committed on its feature branch. Additional profile-specific context routing
passed five focused tests and an 80-test offline suite; all four client
rendering fixtures passed. These tests do not establish live routing.
Automatic execution approval review exhausted its allowance, preventing
new remote/GPU checks, deployment and protected Git operations. No new
actual OpenCode, Portainer or reboot result is claimed after this block.
See [the session completion record](session-summary-2026-10-06.md).

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
| [20261006-geekom-fresh-baseline-sequence](../research/benchmarks/20261006-geekom-fresh-baseline-sequence.json) | runtime / device checks | see artifact |
| [20261006-geekom-fresh-coding](../research/benchmarks/20261006-geekom-fresh-coding.json) | coding | 7/7 stored rows passed |
| [20261006-geekom-fresh-final-quality-sequence](../research/benchmarks/20261006-geekom-fresh-final-quality-sequence.json) | runtime / device checks | see artifact |
| [20261006-geekom-fresh-long-memory](../research/benchmarks/20261006-geekom-fresh-long-memory.json) | telemetry | 172 samples |
| [20261006-geekom-fresh-long](../research/benchmarks/20261006-geekom-fresh-long.json) | long | 1/1 stored rows passed |
| [20261006-geekom-fresh-q8-concurrency3-latency-memory](../research/benchmarks/20261006-geekom-fresh-q8-concurrency3-latency-memory.json) | telemetry | 44 samples |
| [20261006-geekom-fresh-q8-concurrency3-latency](../research/benchmarks/20261006-geekom-fresh-q8-concurrency3-latency.json) | runtime / device checks | 12/12 stored rows passed |
| [20261006-geekom-fresh-q8-single-latency-memory](../research/benchmarks/20261006-geekom-fresh-q8-single-latency-memory.json) | telemetry | 44 samples |
| [20261006-geekom-fresh-q8-single-latency](../research/benchmarks/20261006-geekom-fresh-q8-single-latency.json) | runtime / device checks | 10/10 stored rows passed |
| [20261006-geekom-fresh-rag-memory](../research/benchmarks/20261006-geekom-fresh-rag-memory.json) | telemetry | 4 samples |
| [20261006-geekom-fresh-rag](../research/benchmarks/20261006-geekom-fresh-rag.json) | rag | 10/10 stored rows passed |
| [20261006-geekom-fresh-tools-memory](../research/benchmarks/20261006-geekom-fresh-tools-memory.json) | telemetry | 6 samples |
| [20261006-geekom-fresh-tools](../research/benchmarks/20261006-geekom-fresh-tools.json) | tools | 10/10 stored rows passed |
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
| [20261006-rtx-fast64-solo-mixed30](../research/benchmarks/20261006-rtx-fast64-solo-mixed30.json) | sustained-mixed | 346/346 stored rows passed |
| [20261006-rtx-final-shadow-canary](../research/benchmarks/20261006-rtx-final-shadow-canary.json) | runtime / device checks | PASS |
| [20261006-rtx-final-vision-sequence](../research/benchmarks/20261006-rtx-final-vision-sequence.json) | runtime / device checks | see artifact |
| [20261006-rtx-geekom-client](../research/benchmarks/20261006-rtx-geekom-client.json) | runtime / device checks | PASS |
| [20261006-rtx-media-client](../research/benchmarks/20261006-rtx-media-client.json) | runtime / device checks | PASS |
| [20261006-rtx-ocr-vision-semantic](../research/benchmarks/20261006-rtx-ocr-vision-semantic.json) | runtime / device checks | 20/20 stored rows passed |
| [20261006-rtx-ocr-vision](../research/benchmarks/20261006-rtx-ocr-vision.json) | runtime / device checks | 20/20 stored rows passed |
| [20261006-rtx-peer-client-preflight](../research/benchmarks/20261006-rtx-peer-client-preflight.json) | runtime / device checks | FAIL |
| [20261006-rtx-production-admission](../research/benchmarks/20261006-rtx-production-admission.json) | runtime / device checks | PASS |
| [20261006-rtx-production-opencode-coding](../research/benchmarks/20261006-rtx-production-opencode-coding.json) | coding | 1/1 stored rows passed |
| [20261006-rtx-q4-sequence](../research/benchmarks/20261006-rtx-q4-sequence.json) | runtime / device checks | see artifact |
| [20261006-rtx-retained-sequence](../research/benchmarks/20261006-rtx-retained-sequence.json) | runtime / device checks | see artifact |
| [20261006-rtx-solo-cpu64-latency-memory](../research/benchmarks/20261006-rtx-solo-cpu64-latency-memory.json) | telemetry | 47 samples |
| [20261006-rtx-solo-cpu64-latency](../research/benchmarks/20261006-rtx-solo-cpu64-latency.json) | runtime / device checks | 10/10 stored rows passed |
| [20261006-rtx-solo-description-vision-memory](../research/benchmarks/20261006-rtx-solo-description-vision-memory.json) | telemetry | 34 samples |
| [20261006-rtx-solo-description-vision](../research/benchmarks/20261006-rtx-solo-description-vision.json) | runtime / device checks | 100/100 stored rows passed |
| [20261006-rtx-solo-gpu63-coding-memory](../research/benchmarks/20261006-rtx-solo-gpu63-coding-memory.json) | telemetry | 1 samples |
| [20261006-rtx-solo-gpu63-coding](../research/benchmarks/20261006-rtx-solo-gpu63-coding.json) | coding | see artifact |
| [20261006-rtx-solo-gpu63-latency-memory](../research/benchmarks/20261006-rtx-solo-gpu63-latency-memory.json) | telemetry | 29 samples |
| [20261006-rtx-solo-gpu63-latency](../research/benchmarks/20261006-rtx-solo-gpu63-latency.json) | runtime / device checks | 10/10 stored rows passed |
| [20261006-rtx-solo-gpu63-long-memory](../research/benchmarks/20261006-rtx-solo-gpu63-long-memory.json) | telemetry | 9 samples |
| [20261006-rtx-solo-gpu63-long](../research/benchmarks/20261006-rtx-solo-gpu63-long.json) | long | 1/1 stored rows passed |
| [20261006-rtx-solo-gpu63-mixed30-memory](../research/benchmarks/20261006-rtx-solo-gpu63-mixed30-memory.json) | telemetry | 2 samples |
| [20261006-rtx-solo-gpu63-mixed30](../research/benchmarks/20261006-rtx-solo-gpu63-mixed30.json) | sustained-mixed | FAIL |
| [20261006-rtx-solo-gpu63-rag-memory](../research/benchmarks/20261006-rtx-solo-gpu63-rag-memory.json) | telemetry | 3 samples |
| [20261006-rtx-solo-gpu63-rag](../research/benchmarks/20261006-rtx-solo-gpu63-rag.json) | rag | 10/10 stored rows passed |
| [20261006-rtx-solo-gpu63-tools-memory](../research/benchmarks/20261006-rtx-solo-gpu63-tools-memory.json) | telemetry | 5 samples |
| [20261006-rtx-solo-gpu63-tools](../research/benchmarks/20261006-rtx-solo-gpu63-tools.json) | tools | 10/10 stored rows passed |
| [20261006-rtx-solo-gpu999-latency-memory](../research/benchmarks/20261006-rtx-solo-gpu999-latency-memory.json) | telemetry | 15 samples |
| [20261006-rtx-solo-gpu999-latency](../research/benchmarks/20261006-rtx-solo-gpu999-latency.json) | runtime / device checks | 10/10 stored rows passed |
| [20261006-rtx-solo-q4-coding-memory](../research/benchmarks/20261006-rtx-solo-q4-coding-memory.json) | telemetry | 50 samples |
| [20261006-rtx-solo-q4-coding](../research/benchmarks/20261006-rtx-solo-q4-coding.json) | coding | 10/10 stored rows passed |
| [20261006-rtx-solo-q4-latency-memory](../research/benchmarks/20261006-rtx-solo-q4-latency-memory.json) | telemetry | 15 samples |
| [20261006-rtx-solo-q4-latency](../research/benchmarks/20261006-rtx-solo-q4-latency.json) | runtime / device checks | 10/10 stored rows passed |
| [20261006-rtx-solo-q4-long-memory](../research/benchmarks/20261006-rtx-solo-q4-long-memory.json) | telemetry | 8 samples |
| [20261006-rtx-solo-q4-long](../research/benchmarks/20261006-rtx-solo-q4-long.json) | long | 1/1 stored rows passed |
| [20261006-rtx-solo-q4-mixed30-memory](../research/benchmarks/20261006-rtx-solo-q4-mixed30-memory.json) | telemetry | 359 samples |
| [20261006-rtx-solo-q4-mixed30](../research/benchmarks/20261006-rtx-solo-q4-mixed30.json) | sustained-mixed | 344/344 stored rows passed |
| [20261006-rtx-solo-q4-rag-memory](../research/benchmarks/20261006-rtx-solo-q4-rag-memory.json) | telemetry | 1 samples |
| [20261006-rtx-solo-q4-rag](../research/benchmarks/20261006-rtx-solo-q4-rag.json) | rag | 10/10 stored rows passed |
| [20261006-rtx-solo-q4-tools-memory](../research/benchmarks/20261006-rtx-solo-q4-tools-memory.json) | telemetry | 3 samples |
| [20261006-rtx-solo-q4-tools](../research/benchmarks/20261006-rtx-solo-q4-tools.json) | tools | 10/10 stored rows passed |
<!-- END GENERATED RESULT INDEX -->
