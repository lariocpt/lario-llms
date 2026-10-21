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

Muse and DFlash use Q4 target weights; DFlash has F16 draft KV. Qwen uses Q3 weights. All retained models provide 131072 server / 126976 client tokens. Qwen 64k/256k and 32k choices are retired. Historical DFlash headroom was tight; see the dated benchmarks.

| Registry model / preset | Tokens per slot | Slots | KV |
| --- | ---: | ---: | --- |
| muse-glimmer-dflash / capacity | 131072 | 2 | q8_0 / q8_0 |
| muse-glimmer / capacity | 131072 | 3 | q8_0 / q8_0 |
| qwen3.8 / fast-128k | 131072 | 1 | q8_0 / q8_0 |

Public gateway: :11436. Private backend: localhost :11446.
Select a hardware-prefixed immutable model in OpenCode. `7900xt options` lists
fixed IDs; selecting one uses idle-only owner activation. Busy hardware refuses
a different profile. Legacy inference spellings are migration pins, not mutable
aliases. Client context is server context minus 4096 tokens.

`7900xt start` clears durable Off and starts cold. `7900xt stop` refuses busy work
and persists Off across reboot. Weights load on demand; no startup warmup is
required. The model MCP is read-only. Operator controls are at
https://models.in.drlario.org. See [controls/session identity](../docs/model-control.md)
and the [MCP guide](../docs/mcp-guide.md).

The ROCm image remains pinned in models.json; its dedicated Podman store and weights live on XFS. Boot with the registered OCuLink card attached. Missing hardware never falls back to the laptop iGPU.
