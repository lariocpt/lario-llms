# b70 — active on Bigcachy

Compatible Qwen 128k/256k/512k choices compile to one Q4/Q4 SYCL backend with
per-request thinking, five scheduling slots and a shared context pool. On
2026-10-26 measured memory headroom reduced the configured 655360-token ceiling
to **647168 tokens initially, then 643072 after reload**. The pool is fitted at
load time; live gateway state is authoritative. Admission reserves each selected profile's whole
window, even for a short prompt. This permits four 128k requests, two 256k
requests, or one 512k request, subject to mixed-window accounting. Five scheduling
slots do not guarantee five 128k reservations. Current OpenCode labels say
**shared**; older two-slot/five-slot labels describe previous fixed deployments.

The B70 gateway clears idle KV histories before admitting a new idle-to-busy
burst. Prompt reuse remains disabled: retaining those unusable histories widens
SYCL unified attention and slows unrelated requests. Cleanup is opt-in for this
owner, checks native idleness and fails closed on an unconfirmed erase. The
launcher enables the private native erase API using `--slot-save-path`; the
public gateway does not expose slot actions. No RAM prompt cache is enabled.
Native bypass callers must manage their own idle cache state.

See the [2026-10-26 investigation and measurements](../research/benchmarks/20261026-arcb70/REPORT.md)
for reproducible small/40k/concurrent results, hardware evidence and rollback.
Full-window quality and sustained thermal validation remain pending.

The first activated profile was 256k/two slots.
Initial Vulkan v0.7.0 tiny requests returned OK through the authenticated gateway and native
slots reported 262144 tokens each. The backend is explicitly bound to the xe B70
at PCI 0000:04:00.0; RTX and Intel iGPU/CPU/NPU services remain separate.
**Long prompts proved unusably slow in Vulkan prefill. The activated Arc-only
SYCL/XMX replacement completed a 39412-token input in 83.58 seconds while a
concurrent short request returned in 9.84 seconds. Normal gateway inference
then returned in 0.23 seconds. Full 256k validation remains pending.** Both Arc-only user units are enabled for reboot. OpenCode's allowlist exposes
only the current 128k/five-slot profile; other choices remain hidden pending checks.

Actual driver memory is 31.890625 GiB, below the preparation assumption of 32.
The staged 1696k/two-slot Muse ceiling must be recalculated before activation.
Initial load readings were 43 C package / 46 C VRAM. During a passive one-minute
OpenCode functional check, B70 peaked at 59 C package / 64 C VRAM and RTX at 31 C.
This was a short functional check, not a sustained thermal or speed benchmark.

`install.py` installs only Arc's private keys and units, verifies pinned Q4
weights, and refuses replacing an existing installation. `install_clients.py`
installs per-client inference-only keys after checking the live catalogue. No
management/backend keys are distributed to clients.

## Remaining catalogue preparation

All thirteen catalogue choices use Q4-family GGUF weights and explicit q4_0 K/V.
Smart and Medium share Qwen Q4 weights with xhigh/medium reasoning. Q6 choices
have been removed. Muse Glimmer DFlash adds 256k/twelve slots, 512k/six slots and
a 1696k/two-slot calculated memory ceiling. These are extended-context trials,
not supported-quality claims beyond Muse's native 128k.

`weights.json` pins the three weight files; `budget.py` reproduces the registry
and target/draft allocation estimates. Regenerate with:

```sh
python -m arcB70.budget --write
python -m shared.placements
```

`opencode.prepared.json` enables the owner but allowlists only verified models. See [capacity calculations and limitations](../docs/arcb70-capacity-2026-10-23.md)
and [hardware activation](../docs/hardware-transition-2026-10-23.md).
Intel CPU/iGPU/NPU services remain separate.

## Reproduce the active runtime

Machine-setup `scripts/prepare-b70-runtime.sh` stages signed matching GPU MKL,
builds the separate pinned SYCL commit and compiles the PCI probe on XFS. It does
not activate/restart anything. `llama-server-sycl` verifies the Arc PCI identity,
uses native SYCL/oneMKL attention with CPU-only oneDNN disabled, disables
persistent SYCL caching and preserves explicit Q4 cache configuration.
The old Vulkan launcher/build remains available for rollback. First installation
now checks the prepared SYCL runtime before creating its credentials/units.

See [functional results and limits](../docs/benchmarks-2026-10-23.md).

## Overnight performance task

Give [BENCHMARK AND PERF TEST.md](BENCHMARK%20AND%20PERF%20TEST.md) to an
independent agent for the bounded overnight performance run. Only RAM KV choices
carry the provisional label; naming does not bypass the existing owner gates.

The device precondition now waits up to 60 seconds for the xe render node at boot,
then fails closed if the registered B70 is still unavailable. A device check that
ran too early after the 2026-10-23 reboot had left the backend skipped; starting it
after device readiness restored authenticated inference.
