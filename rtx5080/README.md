# RTX 5080 — bigcachy

16 GiB NVIDIA card, exclusively assigned to one selected profile. Native CUDA llama.cpp
runs behind the `rtx5080.service` user unit and llama-swap :11435. Native serving avoids the
stale NVIDIA CDI library mount found after a driver upgrade. The Docker `vision:8080`
endpoint is now an nginx proxy to the native service, preserving Hermes routing.

Startup warms the `rtx5080` alias from the generated proxy config, so switching
does not first reload the previous selection recorded on disk. The unit allows
31 minutes for startup, covering the 30-minute model warmup budget. `/health`
returns plain `OK`; model APIs return JSON.

`rtx5080` opens a numbered menu. [models.json](models.json) owns three profiles:

- `ocr`: Qwen3-VL-8B-Instruct Q4_K_M + F16 projector, 32768-token context,
  image-max-tokens 8192, mtmd batch 128. Higher image detail for OCR and picture comparison.
- `describe`: the same vision weights with 65536-token context, image-max-tokens 2048,
  mtmd batch 128. More room for descriptions and multiple video frames; callers extract
  video frames and submit them as images. There is no dedicated video-file API.
- `qwen3.8`: Qwen3.8-27B UD-Q3_K_XL, 262144-token context with KV in host RAM
  (`--no-kv-offload`), text only. A real completion passed with the full configured allocation.

OCR and description intentionally share weights; their image/context budgets differ.
These are tested local choices, not a claim of best quality across every published model.
The official [Qwen3-VL model card](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct)
describes its visual, OCR and video capabilities. Large-image comparison passed on two
2400×1800 inputs; OpenCode image OCR passed. Evidence is in `../research/`.

The selected alias is `rtx5080`, with `vision`, `visual`, and `image` retained. Concrete IDs
can swap the hardware, and clients needing images should select `ocr` or `describe` explicitly.
The one slot is reserved for auxiliary/image work; RAG embeddings do not occupy this card.
The monitor checks native serving and periodically infers against the current concrete profile,
so checking health never switches a text profile back to vision.
