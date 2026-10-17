# Radeon OCuLink migration — 2026-10-17

This report separates hardware inventory, fixture checks and real inference.
Earlier throughput and context measurements remain in [the October 6 report](benchmarks-2026-10-06.md).
The migration preserves model geometry and does not promote experimental profiles.

## Verified hardware and storage

| Item | Observed |
| --- | --- |
| Owner | cachyos-mini-mobile, tailnet 100.103.22.121 |
| Card | RX 7900 XT, AMD 1002:744c, unique ID 255c7a14946751e2 |
| VRAM | 21458059264 bytes |
| Driver | amdgpu, gfx1100 |
| PCIe power states | Idle Gen1 x1; supported load state Gen4 x4; load verification pending |
| Model partition | XFS /mnt/xfs; about 290 GiB available before migration |
| Runtime | Existing rootless Podman/crun; dedicated model image store on XFS |
| ROCm image | ghcr.io/ggml-org/llama.cpp@sha256:d7644fd2a92dfa8e21fba2daa2421ad3c054dfe86cf17d3a037ccf1e0596492e |

Only the registered physical card is admitted. The internal Radeon 780M is not a fallback.
The retained target/drafter/Qwen weight files total 30,655,821,184 bytes.

## Retained profiles

| Profile | Slots × per-slot context | Primary Hermes capacity |
| --- | --- | --- |
| muse-glimmer@capacity | 3 × 131072 | 3 |
| muse-glimmer-dflash@capacity | 2 × 131072 | 2 |
| qwen3.8@fast-64k | 1 × 65536 | 0: below primary context floor |
| qwen3.8@fast-128k | 1 × 131072 | 1 |

The saved starting selection is Qwen 64k. Its experimental label remains.
The earlier DFlash sampled headroom of 0.516 GiB remains a limitation.

## Validation record

- PR #22: 150 offline/loopback tests passed, one skipped; encoder gate checks passed.
- Migration: identity, missing-card, stale-token, busy-stop, experimental-opt-in,
  stopped-owner status, lifecycle discovery and rootless routing fixture checks added.
- All three model files transferred to XFS and passed SHA256 verification; the pinned ROCm image imported into the dedicated Podman store.
- Live Qwen 64k inference and OpenCode passed as recorded below. Other profiles, live MCP lifecycle and physical boot checks remain pending.
- Physical cold boots with and without the eGPU have not yet been tested for this configuration.

## Live Radeon / OpenCode smoke check

The laptop runs OpenCode 2.0.31. Its private consumer key and generated provider
configuration were installed from merged machine-setup main, and the running
OpenCode service accepted `opencode reload`. Both its running model list and a
standalone model list include `7900xt/7900xt` and all retained concrete choices.
A real `opencode run --standalone --model 7900xt/7900xt` returned `RADEON_OK`.
The selected backend remains Qwen 64k so it is available for interactive use.

| Check | Observed |
| --- | --- |
| Compute enumeration | Exactly AMD Radeon RX 7900 XT, 20464 MiB |
| VRAM allocated after warmup | 16,202,002,432 bytes (15.09 GiB) |
| Authenticated request from bigcachy | `RADEON_OK`, 0.326 seconds |
| Short request tokens | 20 prompt / 5 generated |
| Short request generation rate | 27.54 tokens/second |
| Backend / gateway | Both active; enabled for user startup; linger enabled |

These are functional smoke measurements, not a sustained throughput, large-context
or concurrent-slot benchmark. [Structured evidence](../research/benchmarks/20261017-7900-oculink-smoke.json).

Initial rootless startup exposed only the card's render node. ROCm failed to
initialise and llama.cpp silently used CPU despite the proxy reporting ready.
Giving ROCr `/dev/dri` for enumeration and setting
`ROCR_VISIBLE_DEVICES=GPU-255c7a14946751e2` resolved this on the mixed-GPU laptop.
Default seccomp remains enabled. The runtime now runs a compute-device probe
before serving and refuses CPU/iGPU fallback or unexpected devices. Regression
coverage checks those refusal cases. The internal 780M is not used for inference.

## Radeon 128k-only configuration correction

Later on 2026-10-17 the Radeon Qwen 64k option was retired at the user's request.
All retained Radeon models now provide 131072 tokens per slot. Earlier 64k results
above are historical, not the current menu or saved selection.

The active backend was already running Qwen at 131072, but OpenCode's generic
Radeon/Qwen entries still advertised 61440 tokens. This caused early compaction.
All three development client configs now use 126976 tokens for those entries;
supported configuration reloads succeeded without inference restarts. The user
confirmed Bigcachy's active agent changed from 25k at 41% to 35k at 28%.

The sequential migration harness is preserved in `benchmarks/oculink.py`, updated
to test only retained profiles. Run it explicitly on the owner during an agreed
idle testing window; it switches profiles and restores the saved selection. It
was not run during this correction because the user was actively coding.

## Geekom Q8 calculated slot allocation

The four Smart/Medium profiles now request Q8 K and V caches. Based on local
GGUF metadata and a conservative 17-attention-layer estimate, capacity increases
from 4 to 5 slots at 245760 tokens and from 8 to 10 at 122880 tokens. Balanced
uses 4 and 6 slots respectively. Two reservations remain. These are experimental
calculated allocations, not new benchmark results. Flash concurrency is unchanged.
See the [complete assumptions and memory budget](geekom-q8-slot-budget-2026-10-17.md).
The running Flash process was not interrupted; dense runtime measurements follow
in the later reorganization window.
