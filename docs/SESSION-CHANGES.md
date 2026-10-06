# LLM rationalization session — October 5–6, 2026

This record covers the hardware/configuration work and the subsequent optimization
implementation. For live experimental profiles and unfinished deployment gates,
use [OPTIMIZATION-STATUS.md](OPTIMIZATION-STATUS.md), not this overview as an
assertion that everything has been activated.

## Hardware and model ownership

The repo now has geekom, 7900xt, rtx5080 and intel folders. JSON registries generate
GPU/native llama-swap configuration; weights and caches stay on each host's verified
XFS partition. Numbered hardware selectors and legacy main-model/agent-model aliases
follow the selected model. Fleet budgets inspect actual ready process geometry,
subtract reservations and return zero when the host/model is unavailable.

Geekom retains four Qwen3.8 smart/medium/context choices and working Flash Next.
Radeon retains Muse Glimmer, its DFlash variant/draft, and Qwen3.8 Q3 capacity.
RTX owns its entire card under OCR, image/frame description or Qwen3.8 Q3 selection;
it is no longer split with embedding inference. CUDA/Vulkan/ROCm flags and installed
binaries were verified. Draft weights, vision projectors and Flash shards are retained.

## Intel workloads and clients

Actual Core Ultra 9 285K capabilities were inspected and OpenVINO software/device
options researched and tested. Matching Runtime/GenAI/tokenizer ABI is pinned.
BGE-M3 FP16 runs on CPU and preserves the existing embedding model, CLS pooling,
L2 normalization, 1024 dimensions and 8192-token input; no RAG vector-space replacement
or reindex was needed. Whisper large-v3-turbo FP16 runs on NPU, Qwen3-8B INT4
translation on the iGPU, and Kokoro INT8 TTS on CPU with espeak support. Intel Qwen
coding/provider provisioning was removed as requested; the translator remains.

Seven Intel workload tools are available through the shared MCP client in OpenCode
and Hermes. Service units, XFS mount requirements, setup and boot-health checks are
source-controlled. Portainer's server and two fleet agents were verified healthy.

OpenCode sources are shared/per-machine in machine-setup; actual online-host
settings were rendered and real OpenCode inference tested. Hardware aliases and
safe context/image capability declarations are explicit. The accidental home Git
repo behind excessive indexing was removed, and model switches do not restart
OpenCode. New private client fragments support admission credentials and conservative
GPU context bounds. Rendered secret-bearing files and backups are mode 0600.

## Verified cleanup and retirement

Only downloads outside the retained model/runtime inventory were deleted. The audit
protected active/selectable weights, cache blobs, draft models, projectors and split
shards, verified XFS and re-audited afterward. Allocated bytes removed: 361.6 GB on
bigcachy, 434.3 GB on l-dev-ai (795.9 GB combined). Both final audits had zero further
candidates. Filesystem free-space changes can differ under concurrent activity.
See [MODEL-CLEANUP.md](MODEL-CLEANUP.md) for exact audit artifacts.

Bifrost was checked against real client routes and metadata-only usage aggregates:
no successful chat since August 7, with recent failures. Only its unused container
was removed. Current compose/startup sources omit it and retain the other stack
services. Historical ignored SQLite state remains; Radeon was not restarted.

Cline CLI and VS Code extension provisioning were removed from machine-setup and
niri-post-setup. Cline 3.0.46 was uninstalled on both model hosts. The tools installer
already had no Cline provision path and records the audit. Existing editor/Cline
conversations and credentials were kept. No unrelated editor extensions were removed.

## Optimization implementation

Resource presets retain original maximum-context capacity choices and add explicit
experimental alternatives. Geekom's three-slot Flash candidate preserves each
245760-token window while recovering measured memory headroom. RTX q8 GPU KV at
32k/64k improved measured decode; failed 128k startup rolled back and that preset
is disabled. Radeon testing was released on October 6. Matched 32k q8 CPU/GPU-KV
tests measured median long-prompt decode of 7.185 versus 29.397 tokens/s, with
17.440 versus 13.554-second TTFT. Ten tool cases passed on each. GPU-KV 64k
recalled all three markers at 61450 actual prompt tokens; the 128k candidate
passed all ten real OpenCode coding, tool and RAG cases. It also
recalled all three markers at 126986 actual prompt tokens, with 255.763-second
TTFT and at least 2.653 GiB observed VRAM headroom. A matched 128k comparison
measured 7.206 versus 29.423 tokens/s CPU/GPU decode. Maximum 262k CPU-KV capacity
remains the saved profile to restore after testing;
these bounded results do not complete the mixed-load promotion gates.
Plain Muse and DFlash each passed all ten actual OpenCode coding cases and ten
two-step tool cases. Their median coding-case wall times were 78.587 and 36.730
seconds in shared-service runs with different slot counts. DFlash's initial
ten-minute sample retained only 0.516 GiB VRAM headroom, below the proposed
1.5-GiB target; plain Muse retained 2.142 GiB. Short-output latency runs still
exhausted output in reasoning: at a 1024-token cap, plain Muse returned final
content in 3/10 cases and DFlash in 0/10. These failures are preserved and no
effective Muse thinking cap or promotion is claimed. Radeon Qwen capacity was
restored safely; its shadow admission canary passed without public enforcement.
Controller idle/hold refusal, actual-process budgets,
startup lock handling and config/selection rollback were checked.

Reproducible synthetic coding, tool, RAG/citation, long-context and vision runners
record actual commands/tokens and separate invalid attempts/affected-case retests.
Memory/zram/pressure/VRAM sampling and real OpenCode checks are retained in research.
These bounded tests have explicit scope limits; they do not establish universal
quality or real-video performance.

Streaming admission source provides separate workload credentials, slot reservations,
fail-closed occupancy reconciliation, cancellation recovery, drain/resume and
resident-only requests. Real Geekom and RTX shadow canaries passed. Private staging,
native rollback deployment, a separate owner-only Radeon container activator,
per-owner Docker fronts and activation-aware boot sources are implemented.
Private preparation now lives on each owner's XFS partition to survive reboots.
The client installer accepts only consumer fragments, preserves other hardware
keys and renders through machine-setup without restarting OpenCode. All 75 root
tests passed. Hermes deployment can resolve its primary fleet credential into a
private .env while generated YAML contains only a reference; direct advisor and
extraction/cron callers also support that workload key. No production admission
activation is claimed: caller rollout and bypass validation
remain completion gates.

The model-selection MCP provides live alias/resident status, numbered choices
and guarded owner switching through existing SSH access. Media/mini-mobile have
status-only access. Bigcachy's runtime registration connected with HTTP204 and
unchanged OpenCode PID. The menu exposes Radeon 32k/64k/128k and RTX 32k/64k
Qwen GPU-KV choices, preserving capacity and disabled RTX128. Geekom Flash now
has an experimental six-slot 131072-token preset, with two coding reservations;
it is source-implemented and not yet loaded/benchmarked. Image-generation/UI
research records the requested Qwen Image 2.1 conversion, compatible ComfyUI/native
runtimes and FLUX.2-klein-4B comparison. No image weights or runtime were installed.

## RTX incident during final verification

During the repeated description workload, CUDA aborted and the kernel recorded
Xid 79 (GPU fell off the bus), followed by Xid 154 requesting OS Reboot.
The upstream PCIe port also recorded a correctable physical-layer receive error
at that timestamp. The shutdown then produced failed TLB invalidations, VA unmaps
and GPU virtual-memory frees, matching the user's observation. This is consistent
with cleanup of an unavailable GPU; it does not prove VRAM exhaustion or identify
a particular card, power, motherboard or driver cause.

The requested bigcachy reboot recovered NVIDIA reporting and actual CUDA
inference. No Xid is recorded in the checked new boot. Read-only device health
guards protect switches, warmups, deployments, benchmarks and admission readiness.
Further RTX stress/switch tests remain deferred while the incident is reviewed.
Recovery does not establish that the fault cannot recur. Timestamped evidence is
in research/rtx-reboot-shutdown-20261006.json; exact root cause remains unknown.

## Repositories, knowledge and remaining work

Changes use personal-repository PRs into main and mesh synchronization. Machine-setup,
desktop post-installer, tools installer, LLM, infrastructure and agents sources are
coordinated. No unrelated shared agents checkout files or live databases were copied.
Hermes knowledge sources and ingest manifest capture this work; real citation-gated
BGE-M3 ingestion and retrieval validate the source checkpoints.

Media opts out of repo sync. After explicit user approval, its private consumer
keys and rendered configuration were installed with mode 0600. Real Geekom/RTX
calls passed; its canonical Intel MCP client discovers seven tools, sees all
four healthy services and ranks a relevant document correctly. Media has no
OpenCode executable, so these checks do not claim a real OpenCode session.
Its machine-level mesh opt-out remains present. No backend/management key was
distributed, and legacy ports still do not enforce admission.
Mini-mobile was unreachable. Production admission rollout, complete promotion
workloads and three physical boot-order tests remain pending. Bigcachy's real
reboot with Geekom online passed: changed boot ID, saved GPU selections, automatic
service startup, all three chat aliases, four actual Intel workloads, managed
OpenCode default/RTX inference, 283 retained and retrievable KB chunks, eight
intact Hermes databases and healthy Portainer server/agents. Geekom's individual
reboot and both cold-start orders are still untested. See docs/BOOT.md and
research/reboot-checkpoint-20261006.json for the exact checkpoint.

The Radeon capacity long-context test completed: 258058 actual input tokens,
all three markers recovered, 1145.809-second TTFT and 0.739 tokens/s decode.
The fast GPU-KV presets provide the practical interactive alternative.

Real OpenCode model-MCP calls passed using structured results and nested-tool
completion checks; 75 root tests passed. Setup PR10 explicitly exposes Code Mode
and is merged. Geekom lists both MCPs connected. Initial test failures remain
recorded; six-slot Geekom switching was safely deferred because inference is
active, so no new geometry or performance result is claimed.

Hermes canonical KB ingest passed its real citation gate and stored 308 chunks
with the unchanged 1024-dimensional BGE-M3 contract. Five actual retrieval
checks found model tools, six-slot choices, image/UI research and Radeon
near-limit results. The Linux-agent MCP is registered in source for its next
normal deploy; its parked container was not restarted for this change.


## Requested local image installation and completed six-slot checks

Both requested image bundles are installed and SHA256 verified on bigcachy's
XFS: Qwen Image 2.1 Uncensored Q4_K_M with its INT8 encoder/VAE, and distilled
FLUX.2-klein-4B BF16 with matching Qwen3-4B encoder/FLUX2 VAE. Pinned ComfyUI,
GGUF loader and isolated CUDA 13 / Torch 2.14.1 runtime are source-backed; the
complete lock has 105 compatible packages. All model/runtime/download/compiler
caches and temporary/output paths are on XFS. `rtx5080 images` and lario_images
MCP implement bounded exclusive-card generation, CPU text encoding and Qwen CPU
image cache, fresh idle/hold/health/RAM checks, no force, and saved-chat restoration.
The image service is on demand, never boot enabled; persisted weights are reused
without downloads after reboot. Actual cold boot tests remain separate.

All four 512/1024px synthetic image jobs passed PNG and saved-selection checks.
At 1024px, Qwen's 25-step job took 46.553 seconds (54.353 including restoration),
FLUX's four-step job 24.293 (30.947 including restoration). Both FLUX jobs used
actual MCP initialize/list/generate. Sampled image VRAM peaks were 5853/8085 MiB;
these single cases/different caches do not establish a general speed or quality
ranking. The image README records memory, global swap and untested edit/alpha/UI
limitations. RTX chat was restored and the final NVIDIA probe remained healthy.

Image MCP was source-rendered on all four clients; bigcachy's native supported
registration connected with unchanged OpenCode PID. Real OpenCode returned both
choices through a completed tool call in 13.198 seconds, with generation disabled
for that test. Geekom lists all three MCPs connected. Media and mini-mobile's
actual discovery exposes image_options only; mini-mobile was reachable for this
rollout, then a later SSH retry failed. No owner credentials were exported.

The Geekom six-slot Flash runtime passed 18/18 short concurrent, 10/10 tool,
6/6 latency and near-limit recall at 126986 prompt tokens. Retained initial
six-way large prompts failed (five timeouts, one HTTP429). Retest minimum RAM
was 19.950 GiB in 15 minutes with 293469 swap-out pages; one tool case took
249.31 seconds. The user clarified only OpenCode was paused during these tests,
so Hermes continued and load is not isolated. Keep the option experimental.

At the user's subsequent explicit request, all Hermes were paused gracefully:
buddha/react-corpus were the two running agents, others were already disabled.
Canonical .fleet-disabled markers preserve this pause through reboots; no data
was deleted and agents must stay paused until the user resumes them. Geekom
then restored its prior balanced three-slot Flash. Root checks pass 81 tests;
all four setup dry runs, 49 setup shell syntax checks and image unit validation
passed. Fresh safe unused-model audits on both hosts found zero candidates.
Portainer public status returned HTTP200/version2.39.5 with server/agent running.
