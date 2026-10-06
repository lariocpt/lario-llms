# Optimization implementation checkpoint — 2026-10-06

Geekom was released for tests. On October 6 the user also released Radeon for
testing and explicitly requested the bigcachy recovery reboot after compaction.
The local Radeon deployment hold has been removed. Bigcachy's reboot with Geekom
online passed the post-boot checks below. The other three boot-order scenarios
remain pending. See research/reboot-checkpoint-20261006.json for the preflight.

## Runtime and measured evidence

Geekom Flash Next currently runs experimental balanced: 3 × 245760 tokens,
two coding reservations and one advisory fleet slot. Equal-input five-repeat
measurements reduced median long-prompt TTFT from 30.299 to 24.614 seconds;
decode rose from 22.36 to 26.88 tokens/s. A completed 30-minute observation
(361 samples) saw available RAM never below 21.714 GiB and zram use at most
2.871 GiB. Swap is zram, not disk swap. The window included bounded workload
batches, rather than 30 minutes of continuous representative mixed traffic.
The initial concurrency-three batch passed 29/30 requests; its affected short
fixture retest passed 15/15. All ten tool cases and 57354-token marker recall
passed. Near-maximum marker recall also passed at 237578 actual prompt tokens, with
889.50-second TTFT. A simultaneous OpenCode coding case timed out at 600
seconds; only the owned test was stopped, and the separate coding/RAG suites were then rerun. This contention failure is preserved; slot reservations do not establish
latency isolation. All ten RAG cases passed with disposable collection cleanup. Nine coding
cases passed; binary_search used valid list.index and was initially rejected
by the evaluator. After the regression-tested allowance, the affected case passed its retest.
All ten coding cases therefore passed across the full run and affected retest,
not a single unchanged ten-case run. Full cross-profile quality comparisons remain untested.

RTX Qwen currently runs experimental fast-64k with q8 GPU KV. Five-repeat
long-prompt TTFT was 5.307 seconds and decode 53.63 tokens/s, versus 8.236
seconds and 8.31 tokens/s with the 262144-token CPU-KV capacity profile.
The 57k-input marker check passed. Minimum observed VRAM headroom was 1551 MiB
(1.515 GiB), close to the proposed 1.5-GiB threshold; this is not a full-load
promotion result. The 32k variant left about 2.7 GiB. The 128k variant failed
upstream startup/warmup, rolled back successfully, and is disabled. The precise
upstream cause is unestablished. Maximum-context CPU-KV remains selectable.

The legacy latency-8k fixture actually used 11036 prompt tokens. Results are
shared-service observations, not isolated throughput or broad quality scores.
Ten tools passed on capacity and 32k. Ten isolated RAG cases passed with a
private disposable collection and verified cleanup. Nine coding cases passed
in the initial full run; the frequency case passed its affected retest after
repairing evaluator handling of valid collection methods and integer JSON keys.
Earlier invalid attempts are retained separately. The 24k marker test passed.

RTX OCR passed all 20 synthetic invoice/frame checks in both runs. The first
strict description run passed all 8 repeated frame checks, invoice IDs/totals,
and 13/20 checks overall; payment booleans are equivalent to the printed NO,
so the grader now accepts them and rejects contradictory/unknown values.
The corrected description retest passed its first six cases, then the CUDA
backend aborted, followed by truncated streams/HTTP 502 for remaining cases.
That incomplete run is not a description quality score. Repeated synthetic
frames do not establish real-video quality.

**RTX incident before recovery:** at 00:36:08 SAST the NVIDIA kernel reported Xid 79
(GPU fell off the bus), then Xid 154 with recovery action OS Reboot. NVML/
nvidia-smi reporting fails. The selector restored Qwen and a bounded completion
still succeeded, but healthy CUDA offload was then unverified. The requested
bigcachy reboot has since recovered NVIDIA reporting and actual GPU inference;
no PCI reset was used. Further RTX stress/switch tests remain deferred while
the incident is reviewed. Root cause is not established; do not attribute
this to OOM, quantization, PSU or driver version without evidence. See
research/rtx-driver-incident-20261006.json and the fetched primary documentation:
[NVIDIA Xid catalog](https://docs.nvidia.com/deploy/xid-errors/analyzing-xid-catalog.html),
[NVIDIA GPU triage](https://docs.nvidia.com/deploy/gpu-debug-guidelines/gpu-node-triage.html).
Controller/deployment/benchmark guards now refuse an unhealthy local NVIDIA
probe before disturbing the running service. Production admission checks device
health with a short success cache and fails closed despite proxy readiness.

## Implemented and staged

Saved hardware presets, numbered selection, actual-process budgets, held/busy
refusal, configuration/state rollback and the native startup-lock regression
fix are implemented. All unpromoted presets are explicitly experimental.

Authenticated streaming admission has separate interactive, fleet, auxiliary,
management and backend credentials; it reconciles actual occupancy, drains,
quarantines cancelled/truncated requests and refuses nonresident model swaps.
Real shadow canaries passed on Geekom and RTX, including overflow rejection,
slot accounting, disconnect recovery and unchanged residency. These separate
loopback gates did not move public ports or prevent legacy backend bypass.

Private staging, a native activation/rollback helper, per-owner Docker frontend
overlays and marker-aware startup sources are implemented. The native helper
refuses Radeon. Gate credentials/unit artifacts remain prepared; **no production
gateway or activation marker is active. Current reservations remain advisory.**
Production activation still needs complete caller credential audits and bypass
checks. Authenticated wildcard public listeners are planned so interface arrival
order does not prevent boot; private backends/children bind only loopback.

Private OpenCode fragments were staged and actual settings rendered on bigcachy
and l-dev-ai, with conservative context bounds and mode-0600 files/backups.
A real OpenCode request using bigcachy's managed configuration returned CONFIG_OK.
No OpenCode restart was performed. Media credential export requires explicit
approval from automatic review and has not happened; mini-mobile is unreachable.
Hermes' deploy source resolves a primary fleet key into the existing private
agent .env and puts only an environment reference in generated YAML. This is
staged integration, not a live agent redeploy. RAG supports a private fleet-key
header; its production credential/container rollout remains pending.

## Retirements and verification

Bifrost's metadata/client audit found the last successful chat on August 7;
recent chat calls failed. Only its container was removed. Active provisioning
omits Bifrost and preserves other LLM/RAG services and historical ignored SQLite
data. Radeon identity/start time was unchanged during removal.

Cline CLI and editor-extension provisioning are retired from machine-setup and
the desktop post-installer. Cline 3.0.46 was uninstalled on both model hosts.
The tools installer already had no Cline install path and records the audit.
Existing Cline conversations/credentials remain. Intel's seven tools remain
in OpenCode/Hermes. Installer PRs 11/5 and machine-setup PRs 7/8 are merged.

All 55 current root tests and three Hermes credential-routing tests passed, including real loopback HTTP. Four
machine-setup dry runs, Python/shell checks and renderer private-file/dry-run
checks passed. The known unrelated missing-link dry-run warnings remain.
Portainer reported 2.39.5 locally and at its configured HTTPS status endpoint,
with server 1/1 and agent 2/2 replicas. Hermes real citation-gated ingestion stored 274 BGE-M3 chunks and retrieval
returned retirement, measured headroom and advisory-versus-enforced facts.
Final checkpoint ingestion/retrieval is performed after result edits.

## Real bigcachy reboot — Geekom stays online

Bigcachy's boot ID changed from 5695d15a-9ce1-40b5-8389-73239687239e to
0c008162-3354-472b-a505-3d61dd49d002. XFS mounted and all four Intel units,
RTX, Docker, infra reconciliation and the Hermes boot unit returned successfully.
The saved Radeon capacity, RTX fast-64k and Geekom balanced selections survived.
Each hardware alias returned BOOT_OK. NVIDIA reports the native llama-server
using 14722 MiB of GPU memory; no Xid is recorded in the checked new boot.
OpenCode returned POSTBOOT_OK through both its managed default and RTX provider.

Real Intel tools produced a normalized 1024-dimensional BGE-M3 embedding,
Portuguese translation preserving negation and 24, CPU Kokoro audio and its
correct NPU Whisper transcription. OpenVINO identifies GPU.0 as Intel iGPU and
GPU.1 as NVIDIA RTX; the translator still explicitly uses the Intel iGPU.
Chroma retained all 283 KB chunks and retrieved the latest authorization record.
All eight Hermes state databases passed read-only integrity checks. Local and
HTTPS Portainer APIs returned 2.39.5, server 1/1 and agents 2/2.

The user's reported shutdown memory errors are confirmed: failed VA unmaps,
TLB invalidations and virtual-memory frees after the earlier bus-loss fault.
They are consistent with cleanup of an unavailable GPU; they do not establish
VRAM exhaustion or the original cause. Exact timestamped examples/counts are
in research/rtx-reboot-shutdown-20261006.json. Recovery is observed, not proof
that the original fault cannot recur.
The NVIDIA upstream PCIe port 0000:00:06.0 recorded a correctable physical-layer
receiver error at the same timestamp as Xid79. The GPU sysfs path confirms that
port is its parent. This is a link-path clue, not a proven component/driver cause.

Radeon baseline Qwen capacity completed five long and five short measurements:
median long TTFT 17.517 seconds / decode 6.318 tokens/s, short TTFT 0.308 /
decode 9.463. The 73-sample observation saw at least 6.522 GiB Radeon headroom.
Matched q8 CPU/GPU-KV comparison presets and stable-PCI AMD telemetry are added.
The separately guarded Radeon activation helper is implemented with rollback;
it has not been activated. Production admission remains advisory/uninstalled.

The matched 32k q8 comparison completed five long/five short runs each: CPU-KV
median long TTFT 17.440 / decode 7.185, GPU-KV 13.554 / 29.397 tokens/s; short
TTFT 0.337 / 0.159 and decode 9.458 / 31.420. Ten tools passed on each.
This demonstrates a gain on those equal-geometry synthetic cases, not a complete
promotion gate. Radeon 64k GPU-KV recovered all three markers at 61450 actual
prompt tokens, with 96.165-second TTFT and 21.740 tokens/s decode. Its observed
VRAM headroom never fell below 5.150 GiB. The 128k GPU-KV candidate passed ten
latency measurements and all ten tools, RAG and real OpenCode coding cases;
near-limit marker evaluation continues. Larger contexts lack a matched CPU-KV
comparison and a full mixed-load run. Maximum-context capacity is retained.

OpenCode's live background server reports healthy version 2.0.22 and PID15911.
Its parsed global configuration includes the newly staged Radeon owner key.
The active API reports three running sessions; no config reload or client restart
was performed. Loaded configuration is not proof of every active client's next
authenticated request. Source client installation accepts only consumer fragments,
preserves unrelated keys, renders through machine-setup and rolls back its private
fragment if rendering fails. Backend/management bundles are refused.

## Completion gates

Full representative workload/quality comparisons, production admission with all
callers and bypass checks, protected Radeon rollout, physical boot-order tests,
and unreachable-host follow-up remain. Do not treat staged source, shadow
canaries, sampled workload windows or a merged PR as those runtime gates.
