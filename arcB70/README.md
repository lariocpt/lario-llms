# b70 — active on Bigcachy

The first live profile is **b70 - 256k 2 slots - qwen3.8 smrt · KV4**.
Pinned Vulkan v0.7.0 returned OK through the authenticated gateway and native
slots reported 262144 tokens each. The backend is explicitly bound to the xe B70
at PCI 0000:04:00.0; RTX and Intel iGPU/CPU/NPU services remain separate.
Both Arc-only user units are enabled for reboot. OpenCode's allowlist exposes
only the verified profile; the other twelve choices remain gated pending checks.

Actual driver memory is 31.890625 GiB, below the preparation assumption of 32.
The staged 1696k/two-slot Muse ceiling must be recalculated before activation.
Initial load readings were 43 C package / 46 C VRAM; RTX remained 30 C and idle.
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
