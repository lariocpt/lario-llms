# Optimization implementation checkpoint — 2026-10-06

Geekom was released for tests. On October 6 the user also released Radeon for
testing and explicitly requested the bigcachy recovery reboot after compaction.
The local Radeon deployment hold has been removed. No new Radeon benchmark or
physical reboot is claimed yet; post-boot validation and the four boot-order tests
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

**Current RTX incident:** at 00:36:08 SAST the NVIDIA kernel reported Xid 79
(GPU fell off the bus), then Xid 154 with recovery action OS Reboot. NVML/
nvidia-smi reporting fails. The selector restored Qwen and a bounded completion
still succeeded, but actual healthy CUDA offload is unverified. No host reboot,
PCI reset or Radeon interruption was performed. Further RTX stress/switch tests
are deferred until recovery. Root cause is not established; do not attribute
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

All 48 root tests and three Hermes credential-routing tests passed, including real loopback HTTP. Four
machine-setup dry runs, Python/shell checks and renderer private-file/dry-run
checks passed. The known unrelated missing-link dry-run warnings remain.
Portainer reported 2.39.5 locally and at its configured HTTPS status endpoint,
with server 1/1 and agent 2/2 replicas. Hermes real citation-gated ingestion stored 274 BGE-M3 chunks and retrieval
returned retirement, measured headroom and advisory-versus-enforced facts.
Final checkpoint ingestion/retrieval is performed after result edits.

## Completion gates

Full representative workload/quality comparisons, production admission with all
callers and bypass checks, protected Radeon rollout, physical boot-order tests,
and unreachable-host follow-up remain. Do not treat staged source, shadow
canaries, sampled workload windows or a merged PR as those runtime gates.
