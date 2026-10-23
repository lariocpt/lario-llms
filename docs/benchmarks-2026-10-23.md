# B70 bring-up and thermal checks — 2026-10-23

This iteration prioritised working inference. **No throughput benchmark, full-window
quality test or sustained thermal-stability test was performed.** All results below
are bounded functional checks on the newly installed card.

## Live B70 result

- Bigcachy detects Intel Arc Pro B70 at PCI 0000:04:00.0, ID 8086:e223, xe driver.
- The OS maps a full 32 GiB memory BAR. Explicit PCI capability decoding requires
  sudo; the full aperture provides evidence that the intended large BAR is active.
- Driver-reported usable GPU memory: 31.890625 GiB. Earlier prepared estimates
  assumed 32; the staged Muse 1696k/two-slot ceiling must be recalculated before use.
- Native Vulkan llama.cpp v0.7.0, exact pinned commit
  620d2225cc436ab0b001e3200e590e3b286ef9ab, is bound only to vendor 8086/device e223
  and discrete type. Missing/ambiguous devices fail closed; no iGPU/RTX fallback.
- Pinned Qwen Q4 weights were copied from the existing Geekom XFS store and
  verified against their SHA256. No replacement of the Geekom backend occurred.
- First authenticated **b70 - 256k 2 slots - qwen3.8 smrt · KV4** request returned
  OK. Native child slots each reported 262144 tokens; OpenCode limit is 258048.
- Actual OpenCode inference returned **B70 OK**, with no tool use or file edits.
- The profile is selectable on Bigcachy, l-dev-ai and mini-mobile. Each client has
  a separate registered inference-only key, checked against the live gateway.
- The other twelve B70 profiles are disabled in owner policy and excluded by the
  client allowlist until checked. They are not certified by the first profile test.

## Separate devices and reboot behavior

Arc has its own arcB70.service backend, lario-admission@arcB70.service gateway,
loopback backend port 11447, public authenticated port 11437 and independent
control state. Both units are enabled; the XFS mount, physical device and durable
Off intent are checked before starting. The proxy starts cold and loads the saved
fixed profile on its first valid request. Actual cold-boot validation remains pending.
The RTX backend was not restarted or used for the Arc test. Existing Intel CPU
embedding, NPU Whisper, iGPU translation and CPU TTS health checks remained healthy.

## One-minute passive thermal observation

The B70 is installed above the RTX with a gap between cards. Both were monitored
while only Arc inference was exercised; no artificial simultaneous GPU workload,
fan override or power-limit change was applied.

| Observation | B70 package | B70 VRAM | RTX GPU |
| --- | ---: | ---: | ---: |
| Initial idle | 37 C | 42 C | 30 C |
| First short model load/request | 43 C | 46 C | 30 C |
| Peak over 30 samples / 60 seconds during OpenCode check | 59 C | 64 C | 31 C |

The initial B70 fan was 1404 RPM, rising to 1536 RPM after first load; RTX was
idle at about 24 W with its fans stopped. These temperatures show no immediate
problem in this short check. They cannot establish sustained case airflow,
simultaneous-load behavior or explain a historical RTX memory fault. Long thermal
tests remain a later iteration, one GPU at a time as requested.

`arcB70/thermal_watch.py` provides passive paired telemetry; it never infers,
switches models or changes cooling/power settings. Arc temperature, fan and power
telemetry and live model context/slots are also exported to Prometheus/Grafana.

Evidence: [sanitized bring-up receipt](../research/software/20261023-arcb70-bringup.json).
See [model guide](guide.md), [MCP guide](mcp-guide.md),
[B70 preparation limits](arcb70-capacity-2026-10-23.md) and
[earlier benchmark results](benchmarks-2026-10-17.md).

## Capacity-exhausted investigation

During live use, the owner ledger and native server both showed two genuinely
processing primary requests, with no model-load error. This profile's maximum
is two requests in parallel. Additional requests (including background work
from an OpenCode conversation) receive HTTP 429 hardware_capacity_exhausted;
the current gateway does not queue them. This is admission saturation, not
a VRAM fault or stale slot count. A slot is an inference request, not a session.

Context cache is allocated for the fixed 256k/two-slot geometry even when the
current prompts are shorter. A third 256k Q4 cache slot would require about
34.20 GiB including weights and the selected reserve, exceeding the board's
31.89 GiB usable memory. The initial investigation preserved both requests; the later approved SYCL
replacement cancelled only those two B70 requests.

## Long-prefill regression and Arc-specific replacement

The initial tiny OK checks did **not** establish usable long-prompt inference.
Two real coding requests remained in prompt processing with zero generated
tokens after more than fifteen minutes. Native slot counters advanced slowly:
this was prefill starvation, not merely a third request hitting the two-slot
limit. Native prompt counters describe the processed/cache buffer, not the
complete original prompt length. No GPU reset or memory-fault evidence was found.

The upstream host PCIe link reports **32 GT/s x8 (Gen5 x8)**. The apparent
Gen1 x1 reading on the GPU's internal bridge is not the negotiated host link.
Do not diagnose host bandwidth from the endpoint reading alone.

The activated Arc-only SYCL/XMX replacement was built at exact upstream commit
d81d0d8fb95e52a66992bcfc212b1891b4d2f94a (PR 29864). Geekom and RTX pins are
unchanged. Build prerequisites include GPU-offload MKL, separate from CPU MKL.
The signed, checksum-pinned matching GPU package is staged on XFS without
changing /opt. Explicit MKL include/package paths prevent stale CPU-only CMake
discovery. System oneDNN is CPU-only, so the candidate disables oneDNN and uses
native SYCL/oneMKL attention. Q4 KV storage and the existing profile identity
remain unchanged. PCI-selected device filtering excludes the Intel iGPU.

The approved B70-only replacement cancelled the two stalled requests, preserved
conversations/files and kept admission paused until checks passed. The first
SYCL warmup crashed with persistent kernel caching enabled. The pinned upstream
SYCL guide warns against this option; disabling persistent caching produced
successful warmup and subsequent requests. No cache directory was deleted.

| SYCL functional check | Input tokens | Elapsed | Result |
| --- | ---: | ---: | --- |
| Cold warmup / compilation | 16 | 56.39 s | OK |
| Synthetic substantial prefill | 39412 | 83.58 s | OK |
| Short request concurrent with prefill | 16 | 9.84 s | READY |
| Normal authenticated gateway after Resume | 17 | 0.23 s | OK |

Native slots remained 262144 tokens each, Q4 K/V and two slots. Admission was
resumed and normal client inference verified. The immutable profile ID is
unchanged, so existing OpenCode selections need no migration. Cancelled turns
can be retried. No other model owner was restarted. The 39k functional result
confirms progress/responsiveness at that size; it does not establish full 256k
quality, maximum-window latency or a controlled speedup against Vulkan.

A spot reading immediately after prefill was B70 package 65 C, hottest VRAM
80 C. This is not a sustained thermal assessment. The explicit opt-in
`arcB70/check_prefill.py` reproduces synthetic checks only while admission is
paused and no client requests exist; it never cancels client work itself.

Evidence: research/software/20261023-arcb70-sycl.json. Runtime preparation is
reproduced by machine-setup/scripts/prepare-b70-runtime.sh; exact upstream and
signed GPU MKL pins are in shared/runtime-versions.json.
