# RX 7900 XT — bigcachy

20 GiB Radeon gfx1100 on PCI 05:00.0. The `agent-llm` ROCm container serves :11436, with
container DNS `agent-llm:8080`. The container receives `/dev/kfd`, the Radeon render node,
and `/usr/share/libdrm`, with no HSA spoof. Its server binary is `/app/llama-server`.

`7900xt` opens a numbered selector. `agent-model` remains a compatibility wrapper.
The hardware alias is `7900xt`, with legacy `agent` and `hermes` aliases retained.
[models.json](models.json) owns these options:

- `muse-glimmer-dflash`: Muse Glimmer 30B UD-Q4_K_XL plus DFlash drafter, two 131072-token
  slots; q8 target KV, f16 draft KV. Keep as the default for agent/tool workloads.
- `muse-glimmer`: the same target weights without the drafter, three 131072-token slots.
- `qwen3.8`: Qwen3.8-27B UD-Q3_K_XL, one 262144-token slot. All model layers on GPU;
  `--no-kv-offload` puts KV in host RAM, preserving card headroom and maximum configured
  context. A real completion passed at that allocation; it does not establish long-context
  answer quality or latency at a full 262k prompt.

All weights are under `/mnt/xfs/AI_Models/gguf` and exposed as `/models/gguf` in the container.
The shared controller generates `llama-cpp/agent-config.yaml` and `.agent-model` state.
`lario-fleet` reads live slots and reserved slots; these profiles reserve zero, so the
advisory budget follows 2 / 3 / 1. Independent sessions can exceed an enabled-agent budget;
overflow receives retryable 429 instead of invisible queueing.
