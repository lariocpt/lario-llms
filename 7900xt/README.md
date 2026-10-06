# RX 7900 XT — bigcachy

20 GiB Radeon gfx1100 on PCI 05:00.0. The `agent-llm` ROCm container serves :11436, with
container DNS `agent-llm:8080`. The container receives `/dev/kfd`, the Radeon render node,
and `/usr/share/libdrm`, with no HSA spoof. Its server binary is `/app/llama-server`.

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
workload reservations are not enforced until production admission is activated.

The numbered menu exposes `qwen3.8@fast-64k` and `qwen3.8@fast-128k` alongside
plain Muse and DFlash. Smaller windows can advertise zero primary Hermes capacity
below its supported floor. The conservative bare-Qwen fallback is 64k, while the
capacity menu is reserved for the two Muse choices. No CPU comparison preset is
selectable now; its historical measurements remain preserved.

See [benchmarks](../docs/benchmarks-2026-10-06.md) for measured results, stability
and promotion decisions, and [the MCP guide](../docs/mcp-guide.md) for switching.
