# arcB70 — Bigcachy Intel Arc B70

Prepared provider for the incoming 32 GiB B70 alongside RTX. Hardware identity,
runtime and allocations still require verification after installation.

All thirteen prepared choices use Q4-family GGUF weights and explicit q4_0 K/V.
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

`opencode.prepared.json` keeps the provider disabled. Inventory/metrics and the
model page show preparation only. See [capacity calculations and limitations](../docs/arcb70-capacity-2026-10-23.md)
and [hardware activation](../docs/hardware-transition-2026-10-23.md).
Intel CPU/iGPU/NPU services remain separate.
