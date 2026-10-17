# RX 7900 XT — cachyos-mini-mobile

20 GiB Radeon gfx1100 connected to **cachyos-mini-mobile** through OCuLink.
The `7900xt.service` user unit runs the pinned ROCm image in rootless Podman.
The authenticated gateway serves :11436; the backend is localhost-only :11446.
Bigcachy's optional `radeon-forwarder` preserves Docker `agent-llm:8080` callers.

Boot detection matches the registered card's unique ID, device ID and VRAM and
resolves its render node dynamically. No fixed PCI address, `renderD128`, HSA
spoof or internal-GPU fallback is used. Absent-card boots skip inference cleanly.
ROCr receives the DRM directory for mixed-GPU enumeration;
`ROCR_VISIBLE_DEVICES=GPU-<registered unique ID>` restricts compute to this card.
Startup requires llama.cpp to enumerate exactly the RX 7900 XT and refuses
CPU fallback if ROCm cannot initialise. Default container seccomp stays enabled.

`7900xt` opens a numbered selector. `agent-model` remains a compatibility wrapper.
The hardware alias is `7900xt`, with legacy `agent` and `hermes` aliases retained.
[models.json](models.json) owns these options:

- `muse-glimmer-dflash`: Muse Glimmer 30B UD-Q4_K_XL plus DFlash drafter, two 131072-token
  slots; q8 target KV, f16 draft KV. Both tool and actual OpenCode coding suites
  passed 10/10, but its sampled 0.516-GiB VRAM margin misses the proposed headroom
  gate; this result does not justify promoting the current geometry.
- `muse-glimmer`: the same target weights without the drafter, three 131072-token slots.
- `qwen3.8`: Qwen3.8-27B UD-Q3_K_XL, one 65536- or 131072-token slot with
  q8 KV and all model layers on GPU. The 262144 CPU-KV and 32k options are retired
  at the user's request. Both retained windows share one weight file.

All weights are under `/mnt/xfs/AI_Models/gguf` and exposed as `/models/gguf` in the container.
The shared controller generates `llama-cpp/agent-config.yaml` and `.agent-model` state.
`lario-fleet` reads live slots and reserved slots; these profiles reserve zero, so the
advisory budget follows 2 / 3 / 1. Independent sessions can exceed an enabled-agent
budget; the backend's total concurrency limit can return retryable 429. Separate
workload reservations are enforced when the authenticated admission gateway is active.

The numbered menu exposes `qwen3.8@fast-64k` and `qwen3.8@fast-128k` alongside
plain Muse and DFlash. Smaller windows can advertise zero primary Hermes capacity
below its supported floor. The conservative bare-Qwen fallback is 64k, while the
capacity menu is reserved for the two Muse choices. No CPU comparison preset is
selectable now; its historical measurements remain preserved.

See [benchmarks](../docs/benchmarks-2026-10-06.md) for measured results, stability
and promotion decisions, and [the MCP guide](../docs/mcp-guide.md) for switching.

`7900xt start --experimental` restores the saved experimental Qwen 64k profile;
`7900xt stop` drains and verifies idle before stopping. All three hardware
commands forward to their registered owners. MCP provides the same actions as
`model_start` / `model_stop`, using a fresh status `lifecycle_token`.
Manual stop lasts this boot; startup conditions respect it. Cold boot with the
card connected restores the saved selection. Hot-plug operation is not promised.

The ROCm image is pinned in `models.json`. Its dedicated Podman store and model
files live on XFS; the existing default Podman store is unchanged. Device passing
uses [Podman's documented rootless device handling](https://docs.podman.io/en/latest/markdown/podman-run.1.html).
