# Bigcachy B70 inference investigation — 2026-10-26

The actionable bottleneck was retained idle KV state widening unified attention,
combined with intentionally disabled prompt reuse. The B70 already ran SYCL,
XMX-capable kernels and oneMKL flash attention. Changing GPU backends, reducing
slots or upgrading drivers was not justified.

The B70 gateway now erases idle KV before admitting a new burst when both the
owner ledger and native backend are idle. This removes histories that the
gateway will never reuse. It preserves active requests, profile identities,
context reservations, five scheduling slots, Q4 KV, reasoning settings and the
existing runtime/driver pins. Native bypass callers still manage their own cache
state. No other owner enables this new option.

## Measurements

Every completed matrix request generated exactly 64 tokens. Thinking was
explicitly disabled except in the separate reasoning probes. All measured prompt
cache-hit counts were zero. Long inputs use 1,500 synthetic records; differences
of a few input tokens are from unique prefixes, not truncation. These are warm
measurements, not cold-load benchmarks. No filesystem caches were flushed.
The initial pool was 647168 tokens; automatic load-time memory fitting selected
643072 after the authorized reloads. This 4096-token difference was not a manual
geometry change. The after-run receipts record the latter budget; both retain
five scheduling slots and the same per-profile admission reservations.

| Route / workload | State | Actual prompt tokens | TTFT s | Prompt tok/s | Decode tok/s | Total s |
|---|---|---:|---:|---:|---:|---:|
| Native / small | Initial retained histories | 54 | 0.982 | 55.10 | 3.27 | 20.241 |
| Native / small | Cleared idle KV | 56 | 0.245 | 230.02 | 23.39 | 2.939 |
| Native / ~40k | Initial retained histories | not returned | unavailable | unavailable | unavailable | failed at 300.071 |
| Native / ~40k | Cleared idle KV | 39,443 | 83.753 | 471.10 | 14.49 | 88.102 |
| Gateway / small | Initial retained histories | 54 | 0.993 | 54.91 | 3.27 | 20.238 |
| Gateway / small | Automatic idle cleanup | 56 | 0.234 | 254.33 | 23.31 | 2.936 |
| Gateway / ~40k | Retained histories | 39,441 | 206.685 | 190.91 | 5.05 | 219.150 |
| Gateway / ~40k | Automatic idle cleanup | 39,443 | 83.832 | 471.00 | 14.48 | 88.182 |
| Native / two concurrent small | Evolved baseline cache | 58 each | 0.569–0.570 | 102.30–103.06 | 19.66 each | 3.774 each |
| Native / two concurrent small | Cleared idle KV | 59 each | 0.571 | 104.22–104.26 | 19.83 each | 3.749–3.750 |
| Gateway / two concurrent small | Retained histories | 57 each | 1.144–1.560 | 50.39–53.31 | 5.35–5.45 | 12.924–13.124 |
| Gateway / two concurrent small | Automatic idle cleanup | 59 each | 0.388–0.533 | 160.20–167.96 | 19.26–19.88 | 3.659–3.702 |

The initial native long request hit its deadline and its socket was closed; the
backend drained before any further tests. HTTP 200 headers alone were not counted
as success. Native processing counters subsequently showed approximately 39k
tokens, but there was no completed usage/timing response to claim as a benchmark.
The later gateway baseline was given a bounded 600-second deadline.

Cache state evolves as requests replace histories. In particular the native
concurrent baseline ran after most original large histories had been displaced;
its near-equality to the after result is real. The initial-versus-after table is
not a fixed-cache randomized speedup experiment. Normal gateway long latency
improved 2.49x in the observed states; small decode improved about 7.1x. Neither
factor is a universal speedup guarantee.

### Controlled causal check, without a restart

`cache-state-pinned/requests.jsonl` pins a 39,441-token fresh request to native
slot 0, then sends the **identical** 54-token short request to slot 1 with prompt
reuse disabled. After erasing all idle slots it repeats that short request in
slot 1, in the same running process:

| Other idle state | Short TTFT s | Prompt tok/s | Decode tok/s | Total s |
|---|---:|---:|---:|---:|
| Slot 0 retains ~39k tokens | 0.317 | 171.89 | 14.48 | 4.670 |
| Idle histories erased | 0.219 | 248.58 | 23.33 | 2.919 |

That is a 61% decode-rate improvement from erasure alone. An earlier unpinned
control (`cache-state/`) showed 23.31 versus 23.32 tok/s: slot selection overwrote
the long history itself, so that run did not isolate another slot's retained
state. It is retained as a negative/control result, not presented as evidence of
an erasure benefit. Two independently fresh ~39k native runs processed at
470.96 and 471.07 tok/s before the final 471.10 tok/s repeat.

### Queueing, reasoning and caching

There is no gateway admission queue: saturation returns an error immediately.
There were no active requests/reservations or busy native slots at initial
preflight, and no abandoned processing work was found. Idle slots did retain
191,643, 8,184 and 1,024-token histories. Paused OpenCode clients were not treated
as proof of idleness; both native occupancy and accounting were checked.

Exact queue delay is not separately instrumented. TTFT minus native prompt time
is an upper bound including frontend work, transport, scheduling and sampling.
After the fix this was 1.3 ms native versus 13.7 ms gateway for the small request,
and 28.2 ms native versus 89.1 ms gateway for ~40k. For two concurrent gateway
requests it was 19–182 ms, which includes backend scheduling. Total inference
time was dominated by native work, not gateway polling or admission overhead.
After concurrency aggregate throughput was about 34.6 generated tok/s gateway
and 34.1 tok/s native; per-request decode rates are in the table.

The explicit thinking probe generated 64 reasoning-only completion tokens and
zero visible answer tokens, hitting the output limit. After cleanup it took
3.100 s through the gateway (first reasoning at 0.396 s; first visible content
unavailable), versus 13.553 s in the retained-history baseline. Reasoning-token
accounting here is inferred from all completion tokens belonging to a
length-limited, reasoning-only response; this build does not return a separate
reasoning-token usage field. Mixed reasoning/content counts remain unavailable.
Historical backend logs also showed 1,314–2,403 output tokens at 0.58–1.33 tok/s.
Thus reasoning volume can add minutes even after prefill, especially at deep
contexts. No reasoning budget was reduced to manufacture a speedup.

The gateway deliberately forces `cache_prompt=false`, and `--cache-ram 0`
disables native automatic idle-slot caching/clearing. Consequently long follow-up
histories are reevaluated and their unusable old KV also costs attention work.
This change fixes the second cost. It does not enable prompt reuse or eliminate
the first cost.

## Hardware and runtime evidence

Both source repositories were clean before investigation. Revisions, build
receipt, executable/library hashes and model checksum pin are in `manifest.json`;
selected process environment, original service definitions and DRM allocation
counters are in `machine.json`. No API keys, credential files or full process
environments were saved. The model pin was recorded, not rehashed across 17 GiB.

- PCI `0000:04:00.0`, `8086:e223`, xe: Intel Arc Pro B70, 31.890625 GiB usable.
- Kernel `7.3.0-3-cachyos`; compute-runtime `26.35.39758.10-1.1`; graphics compiler
  `2.41.5-1.1`; Level Zero loader `1.32.0-1`; oneAPI compiler/runtime 2026.0.
- Runtime source is clean at `d81d0d8fb95e52a66992bcfc212b1891b4d2f94a`.
  The binary and libraries were not replaced or rebuilt.
- Original process selected only `ONEAPI_DEVICE_SELECTOR=level_zero:0` after the
  launcher's PCI verification. iGPU DRM had zero compute activity and only tiny
  bookkeeping allocations. B70 had 31,949,596 KiB fully resident in VRAM, about
  434 MiB GTT staging and no system-memory GPU allocation; process swap was zero.
- `dispatch-diagnostic.log` confirms **66/66 layers offloaded**, 15,718.48 MiB
  SYCL model buffer, 11,376 MiB SYCL KV, 748.12 MiB SYCL recurrent state and
  2,899.99 MiB SYCL compute workspace. CPU-mapped input weights (682.03 MiB) and
  host staging/output buffers are normal; they are not CPU KV/layer offload.
- Trace explicitly shows XMX dequant-GEMM availability and `[FA-DISP] MKL` /
  `[MKL-FA]` with Q4 K/V, 256 query tokens, grouped heads and real GEMM timings.
  Short/decode dispatch also shows TILE. Merely setting MKL_FA=1 was not accepted
  as proof. CMake has `GGML_SYCL_DNN=OFF`; the startup banner nevertheless says
  DNNL yes, so the actual dispatch trace is used to establish the attention path.
- Diagnostic environment and INFO verbosity were temporary and removed before
  performance tests. Graphs remain off and persistent SYCL cache remains unset.
- After-test telemetry: package maximum 69 C, hottest sensor 84 C, maximum compute
  clock 2800 MHz, no reported throttle samples. Card energy deltas gave mean
  260.5 W and maximum two-second interval 275.9 W in that test. No fan/power
  settings were changed. Kernel logs were readable and contained no matching xe
  hang/reset/fault/error during investigation. This was not sustained thermal
  certification. The original RTX llama-swap PID 1497 survived throughout.

## Upstream comparison

Current [upstream SYCL documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/backend/SYCL.md)
describes MKL attention and optional graphs. The pinned dispatcher actually
selects MKL for supported shapes with query length >=32 and KV length >=1024;
the existing 256 microbatch already exercises it. The documentation's simplified
batch guidance is not a reason to change microbatch blindly. Graphs are optional
and workload-dependent; neither runtime nor driver upgrades were needed here.

The same driver series has reported [dual-B70 host mirror allocations](https://github.com/intel/compute-runtime/issues/1019)
and [multi-GPU engine wedges](https://github.com/intel/compute-runtime/issues/946).
This isolated single-device process showed neither signature. No speculative
driver workaround was applied.

Upstream reports [hybrid Qwen prompt-cache contamination](https://github.com/ggml-org/llama.cpp/issues/27148),
[idle-cache save stalls](https://github.com/ggml-org/llama.cpp/issues/30252) and
[unified-cache restore ordering failures](https://github.com/ggml-org/llama.cpp/issues/30961).
These are reasons to preserve the existing no-reuse policy during this focused
fix, not proof that every reported bug occurred here. The pinned source directly
shows `get_n_kv()` using padded `used_max_p1()` across unified cells, and disables
`cache_idle_slots` when cache RAM is zero, explaining the measured retained-state
cost without assuming a hardware fault.

## Admission geometry and labels

One shared Qwen runtime is intentional. Its configured ceiling is 655360 tokens,
but measured headroom at load selected 647168, with five scheduling slots. The
post-reload tests and final recorded smoke used 643072; live state is
authoritative because this budget is fitted on each load. The
native per-slot maximum is 524288; the gateway enforces each selected window and
4096-token client margin. Each active request reserves the full selected window,
not just its actual prompt length. `647168 - 524288 = 122880`; rejecting a new
262144-token reservation in that state is correct. The same remainder follows
two 256k reservations. There was no stale reservation to remove.
At the reloaded budget the equivalent remainder is 118784 tokens, and the same
admission rejection is correct.

This measured pool supports four full 128k reservations, two 256k reservations,
or one 512k reservation; mixed windows compete for the same budget. Five slots
do not promise five 128k windows. Current local OpenCode labels and prepared
source labels already say **shared**; older two-slot/five-slot labels are stale
descriptions. README now documents the actual budget and limits. No client
configuration or allowlist was widened.

## Exact changes, checks and reproduction

- `shared/serving/shared_gateway.py`: opt-in idle-to-busy cleanup under the
  admission lock; recheck all native slots, erase only idle nonempty slots, verify
  erase receipts and fail closed on errors. Never clean while requests are
  allocated/running or native occupancy is uncertain.
- `arcB70/models.json`: `shared_serving.clear_idle_kv_on_admission=true`, outside
  profile identity/geometry. All public profiles and backend IDs were verified
  unchanged.
- `arcB70/llama-server-sycl`: private `--slot-save-path` enables native erase;
  owner-only empty directory `~/.cache/lario-llms/arcB70/slots`. Native erase
  initially returned 501 without this flag, which is why the launcher changed.
  No slot states were saved to disk.
- `tests/test_shared_serving.py`: opt-in isolation, no cleanup during active
  bursts, refuse busy native slots, and cleanup failures create no reservation.
- `arcB70/benchmarks/investigate.py`: bounded synthetic SSE timings, actual usage,
  explicit cache-state controls, concurrent requests, telemetry, restoration and
  incremental JSONL records. README documents the live behavior.

44 focused tests passed (`test_shared_serving`, `test_fixed_serving`,
`test_serving_deploy`, `test_sycl_device`), plus Python compilation, launcher
`bash -n` and `git diff --check`. Matrix records contain 26 completed requests and
one failed timeout, excluding separate trace warmups and the final profile smoke.
The startup socket race after the gateway restart was retried after confirming
the service was active; it produced no inference result. The unsuccessful erase
preflight and unpinned negative control remain in the evidence directories.

From the repository, while clients remain paused and owner/native status is idle:

```sh
.venv/bin/python arcB70/benchmarks/investigate.py \
  --routes native gateway --clear-native-idle --timeout 600 \
  --output research/benchmarks/<new-run>
.venv/bin/python arcB70/benchmarks/investigate.py \
  --suite cache-state --routes native --timeout 600 \
  --output research/benchmarks/<new-control>
```

The harness refuses active/uncertain or initially paused/off state, pauses
admission for native tests and restores admission it paused. Run only one harness
at once. Request outputs are capped at 64 tokens and deadlines at 30–900 seconds.
`workload.json` records prefixes/options in later runs; earlier attempts predate
that instrumentation. No full 256k/512k quality tests, five-way or two-long-prompt
concurrency, mixed long/short fairness, Geekom comparison or sustained load test
was attempted. Those remain outside this bounded diagnosis. Native bypass
traffic can recreate retained state; normal gateway traffic is the fixed path.

## Final service state and rollback

`final-state.json` records ready/enabled, admission unpaused, zero requests/busy
slots and no uncertainty. The original **256k Smart** profile was selectable and
returned HTTP 200 with `B70 READY` through port 11437. User OpenCode sessions were
not resumed or altered; the inference profile is available for them. Temporary
systemd diagnostic overrides were removed. No other GPU/service, driver, user
files or related setup-repository files were changed.
After merging, new user work occupied two tracked 256k reservations. A further
256k synthetic smoke correctly received capacity 429 (118784 tokens available).
The profile remained enabled, ready and unpaused; those two requests were left
running. The earlier successful smoke and zero-work receipt are timestamped
pre-merge observations, not a claim that user work cannot resume afterward.

For immediate functional rollback, pause B70 admission, wait for both ledger and
native idle, set only `shared_serving.clear_idle_kv_on_admission` to false (or
remove it), restart only `lario-admission@arcB70.service`, wait for its HTTP socket
and resume admission. This restores the old behavior without a backend restart;
the launcher erase capability can harmlessly remain enabled.

For full source rollback, revert the focused fix/merge commit on a new branch,
review that patch, and repeat the idle B70 gateway/backend restart sequence.
Preserve unrelated later changes and never reset the entire worktree. Reverting
the launcher removes `--slot-save-path`; the empty owner-only slot directory need
not be deleted. Restore original On/Off and pause intent if it differs from this
run's initial ready/unpaused state. Do not restart or cancel a busy backend.
