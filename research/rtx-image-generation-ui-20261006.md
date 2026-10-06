# RTX image generation and UI design candidates — 2026-10-06

This records the original research before installation was authorized. The later
request to install both bundles supersedes the initial single-bundle proposal;
current installation and local results are in
[the image controller README](../rtx5080/image-generation/README.md).
At the time of this research no image weights/runtime or inference were tested.
RTX recovered after reboot,
but its original Xid79/PCIe fault cause remains unknown. Image experiments must
use the exclusive-card controller, idle guards and rollback; text/vision and
diffusion cannot each assume the whole 16-GiB card concurrently.

## Requested Qwen Image download

The linked abenzerps release is a conversion of the upstream Qwen Image 2.1
weights. Its Q4_K_M diffusion file is listed as 4.60 GB, Q6_K as 5.88 GB and VAE
as 676 MB. The supplied INT8 text encoder is 9.35 GB and can be placed in host
RAM. The card recommends ComfyUI plus leejet's ComfyUI-GGUF fork and provides
text-to-image/edit workflow links. This is a plausible 16-GiB experiment with
encoder offload, not a measured peak-memory or throughput result. CPU encoding
has a latency cost that must be measured; file size is not peak VRAM.
[Requested model card](https://huggingface.co/abenzerps/Qwen-Image-2.1-Uncensored-GGUF).

The upstream model has a 7B visual generator and supports image generation,
editing and transparent RGBA output. These make it a candidate for UI mockups,
illustrations and transparent assets; they do not generate functional responsive
UI code. Quality and transparency claims still need local tests.
[Qwen Image 2.1](https://huggingface.co/Qwen/Qwen-Image-2.1).

Native stable-diffusion.cpp also documents Qwen Image 2.1, separate diffusion,
Qwen3-VL text encoder and model-specific VAE files. Image editing with a GGUF
text encoder needs the matching vision projector. Its runtime-maintainer Q4_K
diffusion download is listed as 4.2 GB. Existing retained Qwen3-VL weights may
be reusable with this path after exact format/projector verification; that is
not established for ComfyUI's supplied safetensors encoder. Do not interchange
older Qwen/Wan VAEs or assume GGUF suffixes guarantee runtime compatibility.
[Native runtime guide](https://github.com/leejet/stable-diffusion.cpp/blob/master/docs/qwen_image_2.1.md),
[Runtime-maintainer GGUF files](https://huggingface.co/leejet/Qwen-Image-2.1-GGUF/tree/main).

## Alternative and decision

FLUX.2-klein-4B is a useful fast-iteration comparison. Its official card reports
approximately 13 GB VRAM, text-to-image and multi-reference editing, and shows
four-step generation. Those are upstream claims, not RTX5080 timings. Native
stable-diffusion.cpp documents its Qwen3-4B encoder and FLUX2 VAE. It requires
different companions from Qwen Image; do not download both full bundles before
selecting an initial implementation.
[FLUX.2-klein-4B](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B),
[Native FLUX2 runtime guide](https://github.com/leejet/stable-diffusion.cpp/blob/master/docs/flux2.md).

Start with a pinned CUDA runtime and one Qwen Q4 bundle. Compare seeded 1024px
generation, image edit, exact lettering/layout and transparent-output validity;
record wall time, VRAM peaks and host RAM. Test 2K only after the initial margin
passes. Preserve failed outputs and runtime commits. ComfyUI best matches the
requested conversion's documented workflow; native sd.cpp offers a lighter
service but needs its own compatible file set and verified image/alpha output.

The eventual RTX image selection needs a separate diffusion service/controller
mode and an image-generation MCP/API. It cannot be appended to llama-swap's
chat-only registry as though llama-server could load it. Preserve the existing
RTX alias semantics for chat/vision clients and advertise image generation as a
tool; pause image work until every current RTX caller can handle an unavailable
chat/vision endpoint during the exclusive generation mode.

## UI design workflow

Use existing Geekom Qwen Smart Q8 as an initial React/HTML/CSS design/code
candidate, Flash for iteration, and RTX Qwen3-VL for screenshot inspection.
This is a workflow recommendation, not a demonstrated UI-quality ranking.
Current ten-case coding suites exercise pure Python functions, not frontend
aesthetics, accessibility or responsive behavior. Build a small comparable UI
suite: dashboard, form and landing page; render desktop/mobile screenshots,
check keyboard access/contrast/overflow and review hierarchy/spacing against
the same brief. Use Qwen Image/FLUX for mockups or assets and the coding model
for the functioning interface. Source-controlled examples and evaluation should
precede any claim that a model is best at UI design.
