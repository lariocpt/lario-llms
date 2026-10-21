# RTX 5080 — bigcachy

16 GiB NVIDIA card, exclusively assigned to one selected profile. Native CUDA llama.cpp
runs behind the `rtx5080.service` user unit and llama-swap :11435. Native serving avoids the
stale NVIDIA CDI library mount found after a driver upgrade. The Docker `vision:8080`
endpoint is now an nginx proxy to the native service, preserving Hermes routing.

- `ocr`: Qwen3-VL-8B-Instruct Q4_K_M + F16 projector, 32768-token context,
  image-max-tokens 8192, mtmd batch 128. Higher image detail for OCR and picture comparison.
- `describe`: the same vision weights with 65536-token context, image-max-tokens 2048,
  mtmd batch 128. More room for descriptions and multiple video frames; callers extract
  video frames and submit them as images. There is no dedicated video-file API.
- `qwen3.8`: Qwen3.8-27B UD-Q3_K_XL, 65536-token context with q4 KV on GPU,
  all layers on GPU, text only. Coding/tools/RAG each passed 10/10, near-limit
  recall passed, and 344/344 sustained requests retained at least 2.51 GiB free VRAM.

OCR and description intentionally share weights; their image/context budgets differ.
These are tested local choices, not a claim of best quality across every published model.
The official [Qwen3-VL model card](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct)
describes its visual, OCR and video capabilities. Large-image comparison passed on two
2400×1800 inputs; OpenCode image OCR passed. Evidence is in `../research/`.

| Registry model / preset | Tokens per slot | Slots | KV |
| --- | ---: | ---: | --- |
| ocr / capacity | 32768 | 1 | q8_0 / q8_0 |
| describe / capacity | 65536 | 1 | q8_0 / q8_0 |
| qwen3.8 / fast-64k | 65536 | 1 | q4_0 / q4_0 |

Public gateway: :11435. Private backend: localhost :11445.
Select a hardware-prefixed immutable model in OpenCode. `rtx5080 options` lists
fixed IDs; selecting one uses idle-only owner activation. Busy hardware refuses
a different profile. Legacy inference spellings are migration pins, not mutable
aliases. Client context is server context minus 4096 tokens.

`rtx5080 start` clears durable Off and starts cold. `rtx5080 stop` refuses busy work
and persists Off across reboot. Weights load on demand; no startup warmup is
required. The model MCP is read-only. Operator controls are at
https://models.in.drlario.org. See [controls/session identity](../docs/model-control.md)
and the [MCP guide](../docs/mcp-guide.md).

Qwen Image Q4 and FLUX Klein remain [separate image tools](image-generation/README.md). Image and encoder controllers hold the same RTX lock; the page refuses Off during those jobs. Use their existing tools for job cancellation. Off blocks managed job startup and chat restoration.
