# Optimization status — 2026-10-06

The current configuration is hardware-owned, with generated runtime settings,
profile-aware alias menus and conservative client windows. Radeon is physically
removed and disabled. All nine Hermes agents remain paused with persistent
markers. Geekom eGPU work is deferred. The
[dated report](benchmarks-2026-10-06.md) preserves successful, failed and
interrupted measurements; the [original plan](OPTIMIZATION-PLAN.md) is historical.

## Validated RTX configuration

RTX Qwen has one retained 65536-token window, with all weights and q4 KV on GPU.
At matched context, long decode was 53.608 tokens/s versus q8's 53.753; median
first-content time was 5.251 versus 5.282 seconds. Free VRAM improved by about
1 GiB. Coding, tools and RAG passed 10/10 each; marker recall passed at 61450
actual input tokens. The continuous mixed test passed 344/344 requests over
1802.907 seconds, at most 73°C, at least 2.510 GiB free VRAM and zero swap-in/out.
This profile is selected and no longer experimental.

OCR retains its completed 20/20 synthetic checks. The corrected description
suite passed 100/100 invoice/frame cases, at most 71°C and at least 4.473 GiB
free VRAM, then restored Qwen. These fixtures do not establish arbitrary
real-document or native-video quality. Qwen Image Q4 and FLUX Klein are installed
on XFS and previously completed four actual 512/1024 PNG jobs; a final
post-admission image/restore check remains pending.

RTX production admission is active. The public gateway uses :11435; its
credential-protected proxy and child listen only on loopback :11445/:5802.
Fifteen live checks passed, covering role authentication, nonresident refusal,
private backend/child isolation, shared Docker/public auxiliary overflow and
cancellation recovery without a model restart. A real OpenCode coding retest
and Geekom/media consumer requests passed through this gateway. Monitoring
checks the physical GPU, uses the public auxiliary budget for inference, and
skips active probes when occupancy is busy or unknown.

## Geekom qualification in progress

Flash balanced retains three 245760-token windows, two coding reservations and
one fleet slot. The six-slot choice retains six 131072-token windows, two coding
reservations and four fleet slots. Both retain q8 KV and the existing loading
mode. Neither Flash preset is promoted by partial test results.

A guarded balanced reload increased available RAM from 12.547 to 23.012 GiB
and reduced swap used from 8.916 to 0.982 GiB. This is a retained-allocation
observation, not proof of a leak. Fresh single latency passed 10/10; three-way
latency passed 12/12, with at least 21.902 GiB available and zero swap-out.
Near-limit recall passed at 237578 actual input tokens. Fresh tools and RAG
passed 10/10 each, with at least 21.643 GiB available and zero swap-out.
Fresh coding and continuous three/six-slot gates are still in progress.

Earlier six-way large-request timeouts and HTTP 429 occurred while Hermes
traffic was still active. Settled short concurrency passed 18/18, but the
shared-load 15-minute observation included about 1.12 GiB swap-out and does
not meet the final 30-minute gate. These results remain in the report.

Geekom admission is prepared, with consumer keys distributed, but its public
port still uses the advisory proxy. Activation and actual caller/bypass tests
follow qualification. Scoped loading overrides and rollback exist for measured
comparisons; no speculative loading or KV change has been deployed.

## Radeon retained for later use

The user stopped agent-llm, set restart=no and cleared the xt Compose profile.
Both manual startup and fleet boot now honor enabled Compose services, even if
stale device nodes exist. The registry and retained XFS weights remain available
for a future eGPU installation; absent hardware has zero capacity.

Radeon Qwen retains only 64k and 128k GPU-q8 options alongside Muse plain and
DFlash. The matched 128k CPU-to-GPU comparison improved long decode from
7.206 to 29.423 tokens/s, 4.08×. Its final mixed run passed 166/166 over
1814.745 seconds with at least 2.715 GiB free VRAM, so 128k is validated.
64k passed coding/tools/RAG 10/10 each and near-limit recall, but its separate
sustained run is unavailable with the card removed; its label remains
experimental. DFlash's observed 0.516 GiB headroom misses the 2-GiB Radeon
target and is not promoted.

## Clients, Intel and repository state

All four actual OpenCode configurations contain the five qualified profile
entries. Geekom balanced advertises 241664 client tokens; six-slot Flash
advertises 126976. Exact aliases exist only under the matching preset. A
supported bigcachy reload preserved server PID 47013; no user OpenCode restart
was performed. Three MCP servers were discovered on each remote client.
Media has no OpenCode CLI and keeps its mesh opt-out. Mini-mobile went offline
after its earlier successful install and still requires a final sync.

Intel keeps the matching OpenVINO 2026.4 stack: CPU BGE-M3 with the original
1024-dimensional CLS/L2/8192-token vector contract, NPU Whisper
large-v3-turbo, iGPU Qwen3-8B INT4 translation and CPU Kokoro with espeak-ng.
Seven workload tools are exposed; Intel has no coding alias. The earlier
verified cleanup removed 795.885 GB; fresh audits found zero unused candidates.
Bifrost and Cline provisioning retirements are already merged.

The latest controller/admission suite passes 109 tests, including real local
HTTP checks. Four machine-setup dry runs and three fleet-boot profile tests
passed previously. Final source checks will run after the remaining changes.
Portainer 2.39.5 returned HTTP 200, server 1/1 and agents 2/2. Final PR merges,
mesh sync and citation-gated KB ingestion/retrieval remain pending.

## Reboots and NVIDIA incident

Bigcachy's earlier reboot with Geekom online passed: changed boot ID, mounted
XFS, restored Intel/GPU services, actual OpenCode/Intel/RAG calls, eight healthy
agent databases and Portainer. That predates the final admission/configuration
changes and does not prove their boot recovery. Geekom-only and both cold-start
orders remain pending, with manual power-on available from the user.

The original NVIDIA Xid79/154 and simultaneous parent-port correctable RxErr
indicate GPU/PCIe access loss. Later failed VA unmaps, TLB invalidations and
memory frees were shutdown cleanup after that fault. The root cause remains
unproven. Solo post-removal RTX runs peaked at 73–74°C versus 88°C under earlier
overlapping load; differing loads prevent attributing the change solely to
card spacing. Device guards fail closed on unhealthy NVIDIA reporting. Recovery
and successful stress tests do not establish that the fault cannot recur.
