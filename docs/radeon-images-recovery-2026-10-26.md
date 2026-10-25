# Radeon, vision and generation recovery — 2026-10-26

The Radeon is attached to l-dev-ai as the registered RX 7900 XT. After reset,
its backend and gateway started successfully; there is no CPU/iGPU fallback.
The 32 GiB BAR mapping covers the complete reported 21,458,059,264-byte VRAM
aperture. The displayed BIOS AC-loss policy was Power On; physical AC-loss
recovery remains a separate unperformed test. The user corrected the clock.

## Live inference evidence

Qwen fast-128k uses the existing 64-token microbatch and Q8 KV. No generated
backend YAML, GPU driver, firmware, geometry or model weights were changed.

| Test | Result |
| --- | --- |
| Cold short completion | 26.441 s including model load; RADEON_OK returned |
| Uncached 3,954-token prompt | 9.177 s total; 450.18 prompt tokens/s |
| Repeat of that prompt | 0.623 s; 3,950 tokens reused from cache |
| 160-token generation | 6.385 s total; 26.83 generated tokens/s |
| Warm mini-mobile client completion | 0.938 s, authenticated |
| Bigcachy client completion | 7.483 s, authenticated |
| l-dev-ai client completion | 0.931 s, authenticated |

One 30-second client probe timed out around another host reset/cold-load window;
it was not counted as a pass. Warm follow-up succeeded. These short probes do
not establish 128k quality, peak-memory or sustained PCIe stability.

The supplied slow design session used a previous Radeon profile revision and
showed long waits before tools, historical authentication errors and no completed
screenshot files. Its current profile ID matches the 64-microbatch catalogue.
The other supplied session was on integrated Geekom and contained a historical
context-budget rejection; it was not evidence of a TI image service stall.
No user conversation database was edited or conversation automatically resumed.

## Confirmed image-generation fault and fix

The recovery timer started RTX chat at 00:20:35 while the image controller held
.rtx5080.lock and ComfyUI was encoding a prompt. Because the user units conflict,
this stopped the image worker and caused connection refused. The watcher had
checked operator hold intent but not the actual workload flock.

backend_watch.reconcile now takes the same nonblocking hardware lock before
starting a backend. If held, it reports workload-busy and leaves that workload
alone. A real-flock regression test confirms that no backend start/device probe
occurs. Gateway visibility and durable Off/stop intent remain intact.

Two subsequent qwen-image jobs on the RTX 5080 completed in 52.745 and 46.693
seconds. Both restored the captured chat profile and resumed admission. Timer
ticks at 00:25:47 and 00:27:15 observed workload-busy without stopping generation.

## Vision and tools

The real TI image-description probe completed in 4.406 seconds. The attachment
bridge on Bigcachy and l-dev-ai routed to the TI successfully. Two isolated real
OpenCode tests verified attachment-to-evidence routing (fake owners, no GPU)
and existing exact-run identity/cancellation behaviour.

The shared images MCP now supplies durable responsive screenshot jobs,
paired sequential frontend/brand analysis, status/cancellation, contrast checks,
and the existing TI-first/5080-fallback describe route. Generation stays on RTX
5080. OpenCode attachment support is mediated by the prompt hook; native text
models are not declared as vision hardware.

Local screenshots require Chromium. Mini-mobile and Bigcachy have it; Geekom's
headless installation does not, so vision/attachments work there but local
screenshot capture requires installing Chromium or running capture on a desktop.
The website planning pack contains 38 source pages at 17 widths, with tiled
coverage for long pages, a reviewed brand proposal and two generated concepts.
Its application implementation/deployment is a separate phase.
