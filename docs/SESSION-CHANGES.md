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
passed all ten real OpenCode coding, tool and RAG cases. Its near-limit marker
test is still running. Maximum 262k CPU-KV capacity remains the default fallback;
these bounded results do not complete the mixed-load promotion gates.
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
keys and renders through machine-setup without restarting OpenCode. All 55 root
tests passed. Hermes deployment can resolve its primary fleet credential into a
private .env while generated YAML contains only a reference; direct advisor and
extraction/cron callers also support that workload key. No production admission
activation is claimed: caller rollout and bypass validation
remain completion gates.

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

Media opts out of repo sync. Exporting new client keys to media was blocked by automatic
approval review pending explicit authorization; its credentials remain unchanged.
Mini-mobile was unreachable. Production admission rollout, complete promotion
workloads and three physical boot-order tests remain pending. Bigcachy's real
reboot with Geekom online passed: changed boot ID, saved GPU selections, automatic
service startup, all three chat aliases, four actual Intel workloads, managed
OpenCode default/RTX inference, 283 retained and retrievable KB chunks, eight
intact Hermes databases and healthy Portainer server/agents. Geekom's individual
reboot and both cold-start orders are still untested. See docs/BOOT.md and
research/reboot-checkpoint-20261006.json for the exact checkpoint.
