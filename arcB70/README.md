# arcB70 — Bigcachy Intel Arc B70

Prepared folder and exact intended provider/hardware name for the incoming Arc
B70 Turbo, installed alongside the RTX 5080. Hardware detection, board identity
and runtime validation remain pending installation.

`placement.json` records intended ownership and proposed ports. `models.json`
stages nine calculated Qwen3.8 Smart Q6 / Medium Q4 profiles with quantized KV.
`opencode.prepared.json` exports the same immutable IDs with the provider disabled.
The 512k two-slot choices use RAM KV; GPU-only 512k two-slot does not fit these
weights. See [capacity estimates](../docs/arcb70-capacity-2026-10-23.md).
There is no certified runtime or active provider yet. This discrete GPU is separate
from [Intel CPU/iGPU/NPU services](../intel/README.md).

See [hardware validation and activation](../docs/hardware-transition-2026-10-23.md).
