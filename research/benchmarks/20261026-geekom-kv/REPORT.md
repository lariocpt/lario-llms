# Geekom Qwen idle-KV and concurrency check — 2026-10-26

Retained idle KV exists on Geekom, but a B70-scale performance or concurrency
regression was **not reproduced**. No new Geekom cleanup policy is justified by
these bounded measurements. The original resident Qwen configuration, launcher,
profile IDs, ten scheduling slots, 1572864-token pool and enablement were restored.
The B70 cleanup fix remains active on its owner; it was not blindly copied to
Geekom. No new model was enabled, loaded or configured.

## State and measurements

Geekom on l-dev-ai uses native Vulkan/RADV llama.cpp `620d222` (v0.7.0), Qwen3.8
27B Q4 weights, Q4 K/V, `--kv-unified --cache-ram 0`, ten parallel slots and two
interactive reservations. Public admission is port 11434; private backend 11444.
After the user stopped sessions, both gateway and native occupancy were checked:
zero requests, zero busy slots, no uncertainty, but **371313 retained prompt
tokens**. Before the stop, six idle slots alone retained 233243 tokens alongside
four correctly tracked active requests. Idle history was not mistaken for active
or abandoned inference.

All performance requests used synthetic text, `cache_prompt=false`, temperature
zero, seed 42 and a 64-token output cap. Measured cache reuse was zero. Each
control pinned the long seed to native slot 0 and identical short requests to
different slots, preventing slot selection from overwriting the history under
test. Erasure occurred only with admission paused and all native work idle.
No user request was cancelled.

| Workload / cache state | Actual input tokens | TTFT s | Prompt tok/s | Decode tok/s | Total s |
|---|---:|---:|---:|---:|---:|
| Initial retained-state short | 53 | 0.338 | 157.32 | 11.89 | 5.637 |
| Initial retained-state ~40k | 39440 | 175.257 | 225.07 | 7.52 | 183.631 |
| Fresh ~40k seed | 39440 | 155.948 | 252.94 | 11.53 | 161.413 |
| Short with ~39k idle history | 53 | 0.354 | 150.45 | 12.286 | 5.483 |
| Same short after erasure | 53 | 0.338 | 157.64 | 12.360 | 5.435 |
| Fresh ~80k seed | 79939 | 428.362 | 186.63 | 10.77 | 434.212 |
| Short with ~80k idle history | 52 | 0.356 | 146.90 | 12.226 | 5.509 |
| Same short after erasure | 52 | 0.344 | 152.18 | 12.360 | 5.441 |
| Four concurrent shorts, ~39k idle history | 56 each | 1.044–1.045 | 53.75–53.78 | 9.602 each | 7.605–7.606 |
| Same four after erasure | 56 each | 1.050–1.051 | 53.44–53.47 | 9.770 each | 7.498–7.499 |

Same-process erasure improved short decode by only **0.6% at 39k** and **1.1% at
80k**. All four requests completed successfully in both concurrent controls;
client-observed aggregate throughput was about **33.66 versus 34.14 output
tokens/sec**, a 1.4% difference. These small, single-pair differences do not
establish a material capacity or throughput regression. The unpaired initial
versus fresh long-prompt results are not a causal speedup experiment: cache
layout, warm state and other host load differed. Other GPU workloads were not
stopped to manufacture isolation.

The initial two-concurrent-short baseline also passed: 56 input/64 output tokens
each, about 6.50 s per request, 10.67 native decode tok/s per request. The reasoning
probe generated 64 reasoning-only completion tokens, no visible answer and took
5.95 s, ending at the output cap. Reasoning volume and fresh long-prompt work can
still dominate interactive latency. This investigation does not enable hybrid
prompt reuse or change the reasoning budget.

## Does retained history reduce concurrent volume?

An idle cached slot is reusable and is not an active inference worker. The
gateway charges full selected windows for active requests, not idle histories.
Geekom's fixed KV buffer is allocated at load time; retained tokens occupy cells
inside it rather than allocating another full cache per idle conversation.

The pinned server's `try_clear_idle_slots()` explicitly skips processing slots,
clears an idle history and retries when KV allocation cannot find space
(`tools/server/server-context.cpp`, around lines 1810 and 4332). Thus retained
histories are **evictable**, not a permanent deduction from the ten request slots
or the shared token admission budget. Reclamation can add latency, and this is
not proof that every saturation workload is unaffected.

The pinned Vulkan shaders include fully masked-block skipping
(`ggml/src/ggml-vulkan/vulkan-shaders/flash_attn*.comp`), unlike the dense MKL
attention cost measured on B70. That implementation difference is consistent
with the small Geekom control deltas; no hardware-counter claim is made about
which shader variant ran.

This was a four-way short-request test with a 39k idle history, not ten full
windows or a physically exhausted 1.5M-token pool. Maximum full-window capacity,
fragmentation/purge latency near exhaustion, sustained thermals and p95 latency
remain unmeasured. No advertised concurrency increase or reduction is claimed.

## Flash Next and Muse Glimmer: read-only findings

- Geekom Flash Next has the unified-KV/no-RAM-cache/no-prompt-reuse combination,
  but its owner profiles are disabled after the prior platform incident. It was
  not resident and was not enabled or loaded. A similar configuration alone does
  not establish the B70 performance failure on its Vulkan backend.
- Geekom's Radeon Muse Glimmer/DFlash profiles use separate fixed geometries:
  three/two slots, no shared pool and no explicit `--kv-unified`. Their normal
  gateway path does not force `cache_prompt=false`. Muse was not resident; the
  Radeon owner was serving a different Qwen profile, which was preserved. No Muse
  benchmark or configuration change was made. These findings are not a claim
  that every possible Muse caching issue is ruled out.

The user's final scope was resident Geekom models only. All inactive-model
settings and policy gates were preserved. Tests cover the existing Flash disable
gate and Muse's fixed geometry without activating either model.

## Durable changes, restoration and fleet verification

The durable changes are diagnostic support in
`arcB70/benchmarks/investigate.py` (`--hardware geekom`, bounded record counts,
pinned four-request controls), focused tests and these findings. No model registry
or permanent launcher change is part of the final diff. The native slot-erase
API needed a temporary `--slot-save-path` during testing; it was removed and the
same Qwen pool reloaded only after confirmed idleness. Original admission intent
was restored: enabled, ready and unpaused. The private empty slot directory may
remain; no slot state files were saved. Drivers and runtime binaries were not
replaced, and no other GPU service was restarted.

Actual installed client credentials were used from **Bigcachy, l-dev-ai and
mini-mobile**. All three authenticated against both Geekom and B70 catalogs,
matched existing profile labels/context limits, and returned HTTP 200 with
**KV READY** from the resident Geekom Qwen model. Receipts are `client-*.json`;
`verify-client.py` reproduces those read-only catalog checks and optional tiny
Geekom smoke. These are the three machines with configured Geekom/B70 OpenCode
overlays in machine-setup. No claim is made for unconfigured/offline fleet devices.

No machine-setup change was needed: its existing source overlays and installed
profile IDs/limits already match, and Geekom's installed launcher is a symlink
into lario-llms. Source remains in lario-llms rather than generated service files.
The separate health-monitor agent's changes were preserved and its merged PR #85
is included in the integration base. Subsequent development used an isolated
worktree; only diagnostic-owned files were changed on Geekom.

Raw JSONL usage/timing records, slot snapshots, workload prefixes, passive sensor
readings and restoration state are retained. No user conversation text, full
process environments or API keys were recorded. A 600-second deadline bounded
large requests; all 20 matrix/control requests completed. No full-window pressure
test was attempted. Sensor data includes other AMD devices and is not evidence
that their workloads were controlled.

For reproduction, pause client submissions, verify the owner is idle, and run
the harness with `--hardware geekom --routes native --suite baseline`. Pinned
erasure controls additionally require the temporary authenticated native erase
API and `--suite cache-state` or `--suite cache-concurrency`; do not enable a new
model or bypass its policy to run them. Restore the launcher and original intent
afterward. The controls are not an automatically deployed cache policy.

Rollback of this diagnostic-only change requires reverting its focused source
commit on a branch. There is no new Geekom runtime policy to roll back. The B70
fix has its own [rollback instructions](../20261026-arcb70/REPORT.md).
