# B70 benchmark and performance test — overnight agent task

## Task for Qwen

Implement and run a reproducible benchmark of the Intel Arc Pro B70 on Bigcachy.
Work from `/home/lario/Projects/personal/lario-llms`. Read this entire document,
`arcB70/README.md`, `arcB70/models.json`, `shared/serving/catalog.py`, and
`docs/benchmarks-2026-10-23.md` first. Inspect current code and live state rather
than assuming this document's baseline is still current.

Deliver a reusable harness, raw results, a readable report and practical profile
recommendations. Do not just produce a plan. Spend at most eight hours on the
whole task, including implementation, tests, recovery and reporting. Record
anything blocked or skipped and its exact reason. Do not invent measurements.

This task authorizes synthetic B70 inference and switching among profiles already
enabled by owner policy when B70 is idle. It does not authorize cancelling user
requests, widening owner/client allowlists, installing another runtime, changing
GPU power/fans, rebooting, or modifying other model owners. Profiles blocked by
policy must be reported as blocked; offline memory estimates can still be made.
Leave RAM KV variants provisional. Non-provisional naming is the owner's choice,
not proof that every context size has passed a full-window benchmark.

**Runner dependency:** if you are Qwen running on this same B70, your own turns
consume a slot. Do not pause, unload or switch the backend serving your agent.
Use an independent agent backend for exclusive tests, or run a bounded detached
harness that saves results and restores service without needing another agent
turn. Treat tests while your agent shares B70 as contended, not clean baselines.
Do not benchmark by recursively asking your own model to orchestrate each call.

## Baseline and questions

The current saved profile is Qwen Smart Q4, 128k context per slot, five slots,
Q4 K/V. Read the saved selection and live resident profile again at execution.
The B70 is PCI `0000:04:00.0`, vendor/device `8086:e223`, with about 31.890625 GiB
usable VRAM. Registry allocation estimates still assume 32 GiB. Keep actual
usable memory distinct from estimated consumption.

The Arc-only SYCL/XMX runtime replaced unusably slow Vulkan prefill. Prior
functional observations were 39,412 input tokens in 83.58 seconds, a concurrent
short request in 9.84 seconds, and package/VRAM readings of 65/80 C after prefill.
These are historical observations, not controlled benchmark targets or thermal
limits. Confirm the actual binary, commit, launch environment and device binding.

Answer:

1. What are warm and cold TTFT, prompt processing rate and decode rate?
2. How do those change with prompt length, output length and concurrent slots?
3. Can the five-slot profile handle five useful requests, including long prompts?
4. How responsive is a short request while another request performs long prefill?
5. Does performance decline during sustained load, and how does that correlate
   with temperature, memory, power and clock telemetry when available?
6. Which enabled profile is best for interactive coding and which for throughput?
7. Which larger profiles fail memory, latency, policy, or retrieval-quality checks?

## Implementation and outputs

Add the harness under `arcB70/benchmarks/`, using the existing `.venv/bin/python`
and installed dependencies where possible. Add a CLI with profile selection,
prompt tokens, generation tokens, concurrency, repetitions, timeout, overall
budget, output directory and dry-run controls. Validate these before inference.
Test token accounting, streaming parsing, timeouts and restoration with small
local fixtures; do not write a large test suite that merely mirrors the harness.

Write artifacts under `research/benchmarks/<UTC timestamp>-arcb70/`:

- `manifest.json`: git revision/dirty status, UTC time, host/kernel, PCI identity,
  runtime commit/binary hash, launch flags, model hashes from pinned manifests,
  exact fixed profile IDs and geometry, relevant library/driver versions.
- `requests.jsonl`: one flushed record per attempt, including failed attempts.
- `telemetry.jsonl`: timestamped passive telemetry during the run.
- `summary.json`: aggregates grouped by profile, workload and concurrency.
- `REPORT.md`: measured findings, tables, recommendations, limits and blocked work.
- Sanitized logs and the exact command/configuration needed to reproduce the run.

Use synthetic inputs and known fixtures, not retained private conversations.
Load credentials through existing private helpers. Never print keys, authorization
headers, private environment files or complete process environments into results.
Persist progress after each request so a crash leaves usable evidence.

## Preflight and service handling

These commands inspect state without activating a different profile:

```sh
.venv/bin/python -m shared.serving.control arcB70 status
.venv/bin/python -m shared.serving.control arcB70 catalog
.venv/bin/python -m shared.modelctl arcB70 options
cat .arcB70-selection.json
```

Inspect `shared/serving/control.py` for current operation semantics and
`shared/serving/gateway.py` for admission behaviour. Record enabled/disabled
profiles, current resident profile, On/Off intent, pause state and active work.
Use the catalog's full immutable ID; never guess one from its display label.

Normal authenticated inference uses port 11437. Backend port 11447 is private.
Use the gateway for user-facing measurements. Separate gateway latency and
admission failures from native server timings. Never treat HTTP 429 as a fast
successful inference. Do not claim native throughput from gateway elapsed time.

Do not disturb existing requests. Wait for idle within a bounded preflight
window, otherwise save a blocked receipt. Before any exclusive test, prevent new
admissions using existing controls, wait for requests to drain, and verify both
owner and native state. Use private backend access only within that isolated
window. Record this path separately from normal gateway measurements. Resume
only if this run introduced the pause and original state was unpaused. Handle
SIGINT/SIGTERM and exceptions with a `finally` restoration path and an independent
watchdog for abnormal harness exit. Never blindly resume a previously paused
service or turn on hardware that was initially Off. If initially Off, report the
run blocked pending an explicit maintenance window.

Use managed activation for already enabled profiles. If a profile is rejected,
record the rejection; do not edit allowlists or hand-write backend YAML to bypass
it. Record actual resident context, cache precision and slots after activation.
Restore the original enabled profile and admission intent when finished, if idle.
If another user's work appears, stop scheduling and do not interrupt it to restore.

`arcB70/check_prefill.py` is a historical bounded diagnostic, not this benchmark:
it hardcodes the older 256k profile and writes one fixed output path. Do not run
it blindly against the current five-slot service.

## Workloads and run order

Use a fixed random seed and distinct synthetic records per repetition. Tokenize
using the active model's tokenizer through an available verified interface;
otherwise record requested size as an estimate and use returned prompt token
counts as the actual measurement. Account for chat template tokens, reasoning,
output allowance and the client context margin. Never send input at the nominal
context ceiling without space for output. Detect truncation and context shifting.
A truncated request does not pass a full-context test.

Run a tiny smoke test first. Separate first-use compilation/model load from warm
runs. Do not flush filesystem caches or restart services merely to create a
cold result. If no safe cold load is available, mark cold latency unmeasured.

### 1. Single-request baseline

For the current profile, test approximately 1k, 8k, 32k, 64k and 112k input tokens.
Use 128 and 512 output-token targets. Run one warmup and three measured
repetitions per selected cell. Begin with 1k/128; increase sizes only after each
smaller stage passes. Add a 1024-token decode run at 1k input if budget allows.

Use two suites: thinking explicitly disabled to isolate inference performance,
and the profile's normal reasoning settings for realistic coding latency. Report
visible output and reasoning tokens separately when available. Include a small
synthetic coding task with a deterministic executable test or exact answer.

### 2. Concurrent requests and fairness

Test concurrency 1, 2, 3 and 5 at 1k and 8k input, 256 output tokens. Synchronize
start times with a barrier. Measure per-request latency and batch makespan.
Then test mixed traffic: one 32k/64k prefill plus short requests started two
seconds later. Record short-request TTFT and completion latency, not just whether
both requests eventually finish.

For full-slot pressure, first try five 32k prompts, then five 64k prompts. Attempt
five near-window prompts only after the smaller cases are stable and sufficient
wall-clock budget remains. One extra request beyond the slot count should get a
bounded, documented admission result; do not flood the service. Observe native
processing counts to confirm intended overlap. Account for any harness agent
requests or other contention and mark such runs accordingly.

### 3. Other profiles

Enumerate the registry dynamically. For each already enabled non-RAM profile,
run a small smoke test before expanding. For Qwen, compare Smart versus Medium
only where both can actually be activated. Test 256k/512k/640k contexts in
ascending order and with output headroom; these are candidate measurements, not
promises of usable quality. Muse DFlash has different native context and draft
requirements; capture accepted/drafted token counts and acceptance ratio if the
runtime exposes them. Do not compare raw totals without describing workloads.

Before attempting calculated maximum geometries, reconcile the estimate with
31.890625 GiB actual usable memory and measured runtime allocation. Skip cells
that cannot fit. Do not change immutable geometries to hide a failure. RAM KV
profiles are optional, provisional and last priority; run only if already enabled
for controlled testing. Label all their results provisional and report CPU RAM,
GPU memory and host load separately.

### 4. Retrieval sanity at increasing context

Generate synthetic records with a random unique key/value at 10%, 50% and 90%
positions; ask for an exact value from the records. Use unique values each time
and at least three seeds for selected prompt sizes. Include distractors and a
missing-key question whose correct response is NOT_FOUND. Score exact answers;
record failures, truncation and timeouts. This is a limited retrieval check,
not comprehensive coding or long-context quality certification. Keep these
results distinct from throughput runs so repetitive text/cache hits do not
inflate fresh-prefill results.

### 5. Sustained run

If earlier stages pass, run 30–60 minutes of representative 8k–32k prompts and
256-token outputs with bounded concurrency. Collect telemetry every two seconds
and compare the first and last ten minutes using matched workloads. Allow at
most one sustained run initially; expand only if it answers a concrete unresolved
question within the eight-hour budget. Do not generate simultaneous RTX load.

Inspect `arcB70/thermal_watch.py` for the existing passive telemetry implementation.
Its CLI is limited to 600 seconds, so use bounded chunks or reuse its snapshot
function with failure handling. Missing NVIDIA telemetry must not crash B70
collection. Record missing sensors as unavailable rather than zero. Compute power
from energy counter deltas only when monotonic and with wrap/reset handling.

## Metrics and honest accounting

Use monotonic clocks for durations and UTC timestamps for correlation. Capture
HTTP status, error class, profile ID, requested/actual prompt tokens, cache-hit or
reused prompt tokens, generated tokens, reasoning tokens when exposed, wall time,
first streamed event, first generated token, first visible content, completion
time, server timings and finish reason. Parse SSE incrementally; metadata and
empty deltas do not count as generated text. A reasoning-only response must not
be counted as visible output. A timeout/cancellation is a failed attempt.

Report:

- TTFT and first-visible-content latency separately when reasoning is enabled.
- Native prompt tokens/sec from native timing fields when available; otherwise
  mark unavailable rather than deriving it from total response time.
- Native decode tokens/sec and a separately labelled client-observed estimate.
- Aggregate throughput as total completed generated tokens divided by batch
  makespan; per-request throughput separately. Include failed request counts.
- Median, min/max, sample count and raw samples. Use p95 only with enough samples
  (at least 20); do not imply reliable tail latency from three repetitions.
- Peak/steady temperatures, memory, power and host load where measured, and
  throughput drift correlated with telemetry without assuming causation.

Use unique prompt prefixes for fresh-prefill trials. Run explicit cache-reuse
trials separately. Explain generation runs ending at EOS before their target;
do not claim they generated the requested token count.

## Bounds, stop conditions and recovery

Set a per-request deadline (start at 300 seconds for small requests, at most
1800 seconds for intentionally large cells) and an eight-hour overall deadline.
Reserve the last 20 minutes for cleanup and reporting. Bound concurrency by the
actual profile slots and set a maximum request count before starting.

Stop scheduling on GPU reset/hang, OOM, repeated runtime errors, unexpected
resident/device change, user activity in an exclusive window, or loss of required
monitoring. Use an explicit conservative test abort policy: package >=85 C or
hottest VRAM >=90 C for three consecutive two-second samples. These are chosen
benchmark abort thresholds, not manufacturer specifications. If already near a
threshold at idle, skip the sustained phase. No cooling/power changes are allowed.

Track benchmark request IDs so timeouts cancel only work owned by this harness
through supported controls; closing an HTTP socket may leave inference running.
Never use cancel-all. If request-level cleanup cannot be confirmed, stop and
report it; do not restart a busy backend. Verify no benchmark work remains and
record final service state. A failed profile should produce a useful report,
not an automatic deployment or promotion.

## Final report and completion criteria

The report must state exactly which profiles/workloads ran, skipped or failed;
provide a concise latency/throughput/concurrency table; identify the interactive
and throughput choices supported by the measurements; list the largest tested
usable prompt for each tested profile; explain any unresolved thermal/memory
limits; and include reproduction commands and final restoration evidence.

Verify generated artifacts contain no credentials. Run the harness's focused
tests and relevant existing checks. Do not rewrite unrelated files. Do not commit,
push or deploy automatically. End with measured conclusions and paths to results,
including partial results if policy or runtime issues prevented the full matrix.
