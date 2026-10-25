# LLM rationalisation — session changes

The repositories now describe each hardware owner and its retained workloads.
RTX is the only discrete GPU in bigcachy. Radeon is physically removed and its
container restart/profile disabled; the proposed Geekom eGPU is deferred.
All nine Hermes agents remain paused. The latest completion state and pending
gates are in [OPTIMIZATION-STATUS.md](OPTIMIZATION-STATUS.md).

## Hardware and model configuration

- Hardware registries and generated runtime settings live under geekom,
  geekom7900xt, rtx5080 and intel. Numbered alias menus select exact model/preset
  pairs and show context, slots and fleet allowance. main/agent/vision remain
  compatibility names. Switching checks occupancy, device health and holds,
  saves selection only after successful warmup, and rolls back on failure.
- Geekom retains four dense Qwen smart/medium entries and Flash Next. The
  working Vulkan build supports Flash's qwen4exp architecture. Flash balanced
  has three 245760-token windows; the six-slot option has six 131072-token
  windows. Both reserve two coding slots and reuse the retained XFS shards.
- Radeon retains Qwen 64k and 128k plus Muse plain/DFlash; RTX Qwen retains
  only 64k, plus exclusive OCR/description profiles. Removed context presets
  share retained weights. Radeon weights are preserved for future reuse.
- Intel uses pinned matching OpenVINO Runtime/GenAI/tokenizers 2026.4:
  compatible CPU BGE-M3, NPU Whisper large-v3-turbo, iGPU Qwen3-8B INT4
  translation, and CPU Kokoro INT8 TTS with espeak-ng. The original embedding
  model, CLS/L2 pooling, 1024 dimensions and 8192-token input are preserved.
  Intel has seven workload MCP tools and no coding/chat alias.
- Qwen Image 2.1 Uncensored Q4 and FLUX.2-klein-4B are installed on bigcachy's
  XFS, with pinned encoder/VAE/runtime files verified. CPU encoder/offload
  permits RTX use. Four actual 512/1024 PNG jobs passed; image jobs restore
  the saved chat profile. The final post-admission job remains pending.
- Verified unused downloads removed 795.885 GB: 43 paths on bigcachy and 24
  on Geekom. Fresh audits found zero remaining unused candidates. Shared
  retained weights, image files, databases and conversation data are preserved.

## Measured improvements

RTX Qwen 64k now uses all-GPU q4 KV and is validated. Matched-context decode
was 53.608 tokens/s versus q8's 53.753, while free VRAM improved by about 1 GiB.
Coding/tools/RAG each passed 10/10 and near-limit recall passed at 61450 actual
input tokens. Its sustained run passed 344/344 over 1802.907 seconds, with
at least 2.510 GiB free VRAM, at most 73°C and zero swap-in/out. Three-layer
RAM offload halved decode for little headroom gain and was rejected. The
corrected description suite passed 100/100 synthetic invoice/frame cases;
these fixtures do not establish arbitrary documents or native-video quality.

Radeon matched 128k GPU KV improved median decode from 7.206 to 29.423 tokens/s,
4.08×, then passed 166/166 sustained requests with at least 2.715 GiB free VRAM.
Its 128k choice is validated. 64k passed coding/tools/RAG and near-limit checks,
but its separate sustained gate is unavailable while the card is removed;
its experimental label remains. DFlash's measured headroom misses the target.

Geekom's fresh balanced reload increased available RAM from 12.547 to
23.012 GiB and reduced swap used from 8.916 to 0.982 GiB. This is not proof
of a leak. Fresh single/three-way latency passed 10/10 and 12/12; near-limit
recall passed at 237578 input tokens. Tools/RAG each passed 10/10. The lowest
available RAM in those windows was 21.643 GiB, with zero swap-out. Coding and
continuous three/six-slot gates remain in progress; Flash stays experimental
until qualification completes. Earlier failed/contended results are preserved.

Exact fixtures, limitations, telemetry and failed attempts are in the
[dated benchmark report](benchmarks-2026-10-06.md) and
[readable HTML](benchmarks.html).

## Clients, admission and tools

All four actual OpenCode configurations have the five exact profile entries.
Balanced Flash advertises 241664 client tokens; six-slot Flash advertises
126976. Generic hardware aliases remain conservative. Exact backend aliases
exist only for the selected geometry, preventing a large-window entry from
silently routing to a smaller preset. Supported bigcachy reload preserved
server PID 47013; no user OpenCode restart was performed. Model status/options,
guarded owner switching, Intel workloads and image tools are documented in the
[MCP guide](mcp-guide.md). Remote MCP discovery passed; media has no OpenCode
CLI and retains its Git sync opt-out. Mini-mobile's earlier install and actual
OpenCode call passed; it is currently offline and final sync remains pending.

RTX production admission is active on :11435, with authenticated loopback-only
proxy/child ports :11445/:5802. Fifteen live checks passed: role rejection,
nonresident refusal, private backend isolation, shared Docker/public auxiliary
overflow and disconnect recovery without restarting the model. Actual OpenCode
coding and Geekom/media requests passed through admission. Monitoring checks
GPU health, consumes the public auxiliary budget and skips inference when busy
or unknown. Geekom admission is prepared but inactive until qualification ends.
Hermes consumer credentials were rendered without resuming paused agents.

Bifrost's usage audit supported retirement; active provisioning was removed and
historical code archived. Cline CLI and editor-extension provisioning were
retired across machine-setup, cli-tools-installer and niri-post-setup; those
retirement PRs are merged. The accidental home Git repository was removed at
the user's request after OpenCode indexing was traced to it.

## Boot, cooling and remaining work

Native units require local XFS, retain saved selections and tolerate peer hosts
arriving later. Radeon startup respects the disabled Compose profile, including
fleet boot with stale device nodes. The latest controller/admission suite passes
109 tests and the three fleet-boot regression cases pass. All four setup dry
runs previously passed. Portainer 2.39.5 returned HTTP 200, server 1/1 and agents
2/2. Offline HTML guides were checked at desktop/mobile widths.

Bigcachy's earlier reboot with Geekom online passed actual model, OpenCode,
Intel, RAG, database and Portainer checks. It predates the final changes.
Geekom's reboot and both cold-start orders still require manual power-on and
final verification. Final PR merges, mesh sync and the new citation-gated
Hermes KB ingestion/retrieval follow completed runtime gates.

The original NVIDIA Xid79/154 with parent-port correctable RxErr indicates
GPU/PCIe access loss. Shutdown TLB/unmap/free warnings followed that loss;
VRAM exhaustion and the root cause remain unproven. Earlier overlapping GPU
load reached 88°C; solo RTX sustained runs peaked at 73–74°C after Radeon
removal. Different workloads prevent isolating airflow as the cause. The RTX
link now reports x16. All subsequent GPU testing is sequential.

GEEKOM A9 Mega has two M.2 2280 PCIe 4.0 x4 slots with matching manufacturer
limits. Linux detects one nominal 2 TB Crucial P310; physical vacancy of the
second slot has not been confirmed. No eGPU migration was installed.
