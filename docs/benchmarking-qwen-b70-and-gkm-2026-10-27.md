# Two overnight Qwen benchmarking and optimization runs

This is an operator runbook, not a claim that the full benchmark suite exists or
has run. Enable the working Geekom Flash profile after its basic checks; do not
hold deployment for this work. Dates, measurements and unknowns below are explicit.

## Divide the nights so the coordinator stays available

| Night | Coordinating agent | Hardware under test | Models |
|---|---|---|---|
| 1 | Geekom/l-dev-ai, on a proven Geekom profile | bigcachy B70 only | Qwen3.8-27B and Qwen3.8 Flash Next |
| 2 | bigcachy B70, on its proven profile | Geekom integrated APU only | Qwen3.8-27B and Qwen3.8 Flash Next |

Do not run both nights simultaneously. The coordinating agent and its inference
backend must never be unloaded, reconfigured or benchmarked by its own run. Keep
the RTX available as a fallback coordinator; check its readiness before relying
on it. Use fresh, bounded agent contexts for subtasks and write a handover before
each context ends. A failed local-agent activation is a blocking condition, not
a reason to silently loop or move the agent onto the hardware under test.

All scripts, hypotheses, patches and evidence belong in this repository. Preserve
unrelated work. The external 7900 XT is excluded from the Geekom tests; it lost
its PCIe link on 2026-10-27 and the user powered it off during a reboot.
Flash currently uses different weight quants on the two hosts; do not attribute
cross-host speed differences solely to hardware without a matched-quant control.

## Current baselines to reproduce, not assumptions to extrapolate

- B70 Flash: UD-Q4_K_XL, Q4 K/V, three 262,144-token slots, native llama.cpp SYCL,
  first 40 expert layers and PLE in CPU memory. `--no-op-offload` is essential:
  omitting it produced single-thread expert staging and roughly 60–70 tok/s
  prompt ingestion; enabling it used about 22 cores and reached 150–155 tok/s
  in an 8K case. Three distinct 8,223-token retrievals passed; the cold round
  took 167 seconds and the cached round 1.2 seconds. A real approximately
  200K-history compaction subsequently ran for over 35 minutes and starved
  shorter requests. Short-prompt success does not establish acceptable latency.
- B70 Strata SYCL 0.1.50 and an unpatched 0.1.51 source build stalled in the
  first verify window with batching. Existing failure reports are sufficient;
  do not repeat this unchanged configuration throughout the night.
- Geekom regular Qwen uses native Vulkan. Geekom Flash is being deployed using
  its existing UD-Q3_K_XL files, Q4 KV, four native 262,144-token contexts and
  the official HIP Halo/gfx1151 engine. Read the deployment receipt before use;
  do not turn "being deployed" into a passed benchmark.
  Deployment update: eight native four-slot responses and four authenticated
  gateway checks passed; all three OpenCode clients now offer the profile.
  This establishes no full-window benchmark result.
- B70 evidence: `research/benchmarks/20261027-b70-flash/`.
  Geekom evidence: `research/benchmarks/20261027-geekom-strata/`.

## Admission, ownership and rollback are prerequisites

Run these read-only commands on the coordinator; the control helper routes to
the hardware owner:

```sh
python3 shared/serving/control.py arcB70 status
python3 shared/serving/control.py geekom status
```

Before every controlled load, require both an empty gateway request ledger and
idle native slots. Save the current profile, enabled/disabled policy, configuration
and binary hashes. If user work is active, defer that hardware. Never cancel a
user's compaction or inference to make a benchmark fit its schedule. Wait at most
five minutes for ownership, then record a deferral and end that target's run.

Use the existing owner controls for the agreed hardware, for example:

```sh
python3 shared/serving/control.py arcB70 pause
python3 shared/serving/control.py arcB70 resume
```

Substitute `geekom` for Night 2. Pause blocks new work; it does not prove existing
work has stopped. Recheck native and owner idleness after pausing. Load/unload
profiles using actual catalog IDs; do not fabricate a name or hand-edit runtime
YAML. At the end restore the saved working profile and policy, unless the user
has since issued a manual Off. Keep Geekom profiles physically exclusive when
their combined memory contract has not been proved.

## Build the bounded runner before leaving it overnight

Existing `arcB70/benchmarks/llama_flash_smoke.py`,
`arcB70/strata/smoke.py`, `geekom/strata/smoke.py` and
`arcB70/benchmarks/cpu_monitor.py` are useful building blocks. They are not a
complete orchestrator. First implement a small case runner and verify its timeout,
cancellation, telemetry and restoration paths with mock work. Existing harnesses
restore their previous profile after testing; account for that before scheduling
the next case.

Use direct HTTP/SSE requests to the inference endpoint. Do not use OpenCode as
the timed benchmark client: retries, title jobs, reasoning and compaction can
hide latency and consume extra slots. Every case must have an ID propagated into
HTTP logs, known input-token count, fixed output cap and a finite deadline.
Disable automatic retries in the benchmark client. A coordinator tool timeout
must also terminate its owned remote job; leaving an SSH child behind is failure.
Read the benchmark's authorized credentials privately on the target owner.
Never put keys into prompts, command output, telemetry or git. Use synthetic
benchmark conversations rather than copying users' active session contents.

Use a foreground process group or a uniquely named user scope/cgroup. Retain its
PID, process start time and unit name. Kill only that benchmark group. Never use
`pkill llama-server`, a shared service restart or a host reboot as cleanup.

## Progressive cases and meaningful correctness checks

1. Record the exact model revision/quantization, engine/version/binary SHA,
   GPU PCI identity, driver/kernel, CPU threads, actual context/slot count,
   all arguments/environment and memory before loading. Confirm the correct GPU.
2. Begin with one 1K prompt and a 128-token decode cap, thinking explicitly off.
   Then test two and three concurrent streams; on Geekom include four. The
   request must permit a long enough answer to measure steady decode.
3. Use 8K and 32K distinct prompts, each with its own retrieval needle. Verify
   isolation, correct answers and actual completion lengths. Repeat unchanged
   prompts to measure prefix reuse and cached-token counts. Keep cache policy
   identical between comparison arms. No blanket cache disable or idle-KV erase.
4. Add a long cold prefill while another stream is decoding. Measure per-stream
   token gaps and time to first token of a newly arriving short request. This is
   a required case: aggregate tok/s can hide starvation completely.
5. Advance to 64K, 128K and 256K only after the previous stage is healthy.
   Forecast the next stage from measured prompt throughput. Skip and report a
   case forecast to exceed its deadline; do not spend an hour proving it is slow.
   Full-window retrieval/correctness is separate from allocating a full window.
6. Separately check a representative coding/tool-call exchange at the intended
   reasoning effort, cancellation and immediate recovery, fourth/fifth request
   admission as appropriate, and warm-cache continuation after cancellation.

Use at least three reproducible cold/warm samples for an initial comparison;
collect more only for a promising candidate within budget. Report sample counts
with P50/P95 and label small-sample percentiles. Record TTFT, queue delay, prefill
time, steady per-stream decode, aggregate decode, longest inter-token gap,
prompt/cache/output tokens and correctness. Do not mix thinking tokens with
visible answer speed without reporting both.

## Monitoring and hard stop conditions

- Default **two-hour wall budget per target/night**, including setup and fixes.
  Default **ten-minute maximum per case**. At most one justified retry after a
  failed case, with its reason recorded. Do not rerun an identical failing arm.
- Monitor meaningful progress every two seconds: SSE tokens, native processed
  counters and known client input size. Abort after **60 seconds without any
  meaningful progress**. CPU/GPU utilization alone is not progress. Initial model
  loading may receive a separately bounded three-minute window if bytes/allocations
  demonstrably advance. A single blocking tool call must not defeat the watchdog.
  Run the watchdog on the target host, independently of the agent's own model
  calls, so an unavailable coordinator cannot leave GPU work running indefinitely.
- Distinguish admission wait, prefill and decode. Native `n_prompt_tokens` can
  describe the growing resident sequence rather than the full submitted input;
  derive the denominator from the benchmark's tokenizer. If a request is reissued
  with the same OpenCode turn ID after about five minutes, record the retry loop
  rather than restarting its elapsed-time clock and declaring it healthy.
- B70: monitor its 31.89 GiB VRAM, 125 GiB host memory, per-thread CPU, GPU
  utilization, memory transfers, thermals, clocks and new swap activity. Preserve
  the measured CPU-weight allowance and OS headroom. Capture a short stack sample
  when stalled, not continuous intrusive profiling.
- Geekom: **110,000,000,000 bytes total inference budget**, including CPU/GPU
  copies, sessions, checkpoints and scratch; RAM and UMA/GTT are one pool.
  Read the current GTT cap; the earlier measurement was 105.46875 GiB. Bound
  expert-cache and conversation-cache allocations explicitly. Sample host memory,
  cgroup memory, GTT and swap together without adding overlapping counters.
  A cgroup `MemoryMax` is not proof that every driver allocation is accounted.
  The gateway's calculated memory ledger is not a physical free-memory reading.
- Avoid swap as an operating strategy. Check deltas, not pre-existing swap pages.
  Stop on sustained new swap-in/out, predicted memory overshoot or lost OS
  headroom before trying a larger case. Use bounded prefill chunks initially.
- On GPU reset, device loss, PCIe all-ones config, OOM or a host disconnect:
  stop the run, preserve the last telemetry and mark the hardware unavailable.
  Do not automatically reboot, reset a GPU, change kernel/BIOS settings or keep
  trying models. Restore only when health can be verified; otherwise hand over.

## Optimize one demonstrated bottleneck at a time

Write the hypothesis, evidence, one proposed change and rollback before each
experiment. Examples include expert placement/staging, thread counts, prefill
chunking and scheduling fairness. Preserve weight and KV quantization for the
primary comparison. KV8 or another quant is a separately labelled experiment,
not a silent precision downgrade or a misleading speed improvement.

Compare the candidate against a same-night baseline with identical prompts,
cache state, reasoning and concurrency. Require correctness and no regression
in short-request latency, prefix reuse or cancellation. Reject changes that
improve aggregate throughput by starving an interactive stream. Do not adopt
unverified flags copied between SYCL, Vulkan and HIP.

## Deliverables before each night ends

Write `research/benchmarks/<date>-qwen-<target>/REPORT.md`, per-case JSON/JSONL,
commands and configuration hashes, telemetry, correctness results, failed and
skipped cases with reasons, and before/after owner state. The report must say
which profile is restored, which change is proposed/adopted and what remains
untested. Never claim a benchmark passed from process exit or allocation alone.

Commit reviewable code/config changes on a feature branch only after focused
checks pass; retain a rollback point. Do not push, open a PR, or change fleet
defaults automatically as part of the unattended run. Preserve existing source
and private OpenCode credentials. Finish with a short handover that the next
coordinating machine can resume without reconstructing the conversation.
