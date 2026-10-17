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
