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
- Live transfer, inference, OpenCode/MCP and boot results will be appended after deployment.
- Physical cold boots with and without the eGPU have not yet been tested for this configuration.
