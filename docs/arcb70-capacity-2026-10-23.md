# Arc B70 Q4 capacity preparation — 2026-10-23

This is the current preparation catalogue, superseding the earlier Q6/Q8-KV
candidates. All thirteen profiles remain disabled pending B70 installation.
No model benchmark, allocation or long-context quality test is claimed.

## Quantization policy and software

All target weights use the **Q4 GGUF family**, and target K/V caches use **q4_0**.
Muse's DFlash draft uses the pinned K-quant GGUF and explicit **q4_0 draft K/V**,
not the Radeon profile's f16 draft cache. Q4-family GGUF is a mixed-precision
recipe, not a promise that every tensor is exactly four bits. q4_0 cache blocks
use 18 bytes per 32 values (4.5 effective bits, including scales).

Intel XMX support and GGUF/KV implementation are separate concerns. Q4 reduces
memory requirements but does not prove the fastest backend or long-context
performance. Upstream [SYCL support](https://github.com/ggml-org/llama.cpp/blob/master/docs/backend/SYCL.md)
and [XMX speculative-verification improvements](https://github.com/ggml-org/llama.cpp/pull/29864)
justify an Arc-specific probe. Check that the chosen pinned SYCL build contains
the required changes and supports Q4 target/draft attention on this exact card.
Do not upgrade or restart the working Geekom/RTX backends to prepare Arc.

## Weight provenance and memory budget

`arcB70/weights.json` pins repository revisions, bytes and SHA256 for Qwen Q4,
Muse Q4 and the Muse drafter. Only HF API records and the first 128 KiB of each
Muse GGUF were read; no weights were downloaded for this change. Actual GGUF
geometry is recorded in `research/software/20261023-muse-gguf-headers.json`.

Assume **32 GiB** usable VRAM and reserve **3.5 GiB** for runtime/driver/compute
allocations. Model file sizes approximate resident weights and must be checked
against actual GPU buffers. Reserve adequacy, concurrency and prompt-batch peaks
are unverified; allocated slots may need reducing on the real hardware.
`--fit off` prevents silently shrinking the declared geometry.

- Qwen Q4: 16.3533 GiB; Smart uses xhigh reasoning, Medium uses medium.
- Muse Q4 target: 14.7877 GiB; DFlash draft: 1.5192 GiB; combined 16.3069 GiB.
- Qwen full-attention cache: context × slots × 17 layers × 4 heads × 512 K/V dimensions × 18/32 bytes.
- Muse target: 13 full-attention layers, 2 KV heads, 128 key + 128 value dimensions.
  The other 39 target layers use a 2048-token sliding window.
- Muse draft: five sliding-window layers, 8 KV heads, 128 key + 128 value dimensions.
  Both target and draft ubatches are bounded to 256. Per-sequence sliding buffers
  budget 2048 + 256 cells, padded to 256; no `--swa-full` is allowed.
- Muse cache per slot: `(context × 13 × 2 × 256 + 2304 × (39 × 2 × 256 + 5 × 8 × 256)) × 18/32` bytes.

The draft weights and draft sliding cache are included. Batch feature buffers,
logits, graph allocations and concurrent-work overhead are covered only by the
unverified 3.5 GiB reserve. The math assumes the pinned runtime honors bounded
sliding-window allocation; a runtime with full-size SWA invalidates these counts.

## Calculated profiles

Every choice exclusively owns the card. Slots are concurrent requests on one
resident model, not simultaneous different resident models. Context is per slot;
server `-c` is context × slots. OpenCode context is server context minus 4096.

| Profile | Context | Slots | Cache location | Cache GiB | VRAM including reserve |
| --- | ---: | ---: | --- | ---: | ---: |
| qwen3.8-smart-q4-128k | 128k | 5 | GPU Q4 | 11.953 | 31.806 GiB |
| qwen3.8-smart-q4-256k | 256k | 2 | GPU Q4 | 9.562 | 29.416 GiB |
| qwen3.8-smart-q4-512k | 512k | 1 | GPU Q4 | 9.562 | 29.416 GiB |
| qwen3.8-smart-q4-640k | 640k | 1 | GPU Q4 | 11.953 | 31.806 GiB |
| qwen3.8-smart-q4-512k-ram-kv | 512k | 2 | CPU Q4 | 19.125 | 19.853 GiB |
| qwen3.8-medium-128k | 128k | 5 | GPU Q4 | 11.953 | 31.806 GiB |
| qwen3.8-medium-256k | 256k | 2 | GPU Q4 | 9.562 | 29.416 GiB |
| qwen3.8-medium-512k | 512k | 1 | GPU Q4 | 9.562 | 29.416 GiB |
| qwen3.8-medium-640k | 640k | 1 | GPU Q4 | 11.953 | 31.806 GiB |
| qwen3.8-medium-512k-ram-kv | 512k | 2 | CPU Q4 | 19.125 | 19.853 GiB |
| muse-glimmer-dflash-256k | 256k | 12 | GPU Q4 | 11.406 | 31.213 GiB |
| muse-glimmer-dflash-512k | 512k | 6 | GPU Q4 | 11.188 | 30.994 GiB |
| muse-glimmer-dflash-1696k | 1696k | 2 | GPU Q4 | 12.184 | 31.991 GiB |

Qwen GPU profiles maximize calculated slots: 128k/five, 256k/two, 512k/one,
640k/one for both Smart and Medium. The 512k/two-slot RAM-KV choices keep weights
on Arc but require **19.125 GiB Q4 cache in system RAM**, plus CPU/runtime working
memory. CPU attention/transfers can be slower; they are explicit separate choices.
Two 512k GPU slots still exceed 32 GiB with these weights and reserve.

Muse DFlash: **256k/twelve slots**, **512k/six slots**, and **1696k/two slots**.
A thirteenth 256k slot needs 32.164 GiB; a seventh 512k slot needs 32.859 GiB.
The single-slot calculation gives 3392k. The requested two-slot profile halves
that to **1,736,704 tokens (1696k) per slot**, and recomputes both SWA buffers.
The result is 31.991 GiB including the reserve; the next 32k step per slot
exceeds the budget. This is a memory ceiling, not a recommendation for ordinary
coding; actual buffers may require lowering it.

## Context extension is not context validation

Qwen native context is 262144; Muse and its draft publish **131072**. All requested
Muse profiles therefore extrapolate beyond native training context: YaRN 2× at
256k, 4× at 512k, and 13.25× at the calculated 1696k/two-slot ceiling. No useful-quality
claim is made for those extensions, especially 13.25×. See the publisher's
[native-context guidance](https://dev.meta.ai/docs/muse-glimmer/deploy) and
[target](https://huggingface.co/meta-models/Muse-Glimmer-30B/blob/main/config.json)/
[draft geometry](https://huggingface.co/meta-models/Muse-Glimmer-30B-assistant/blob/main/config.json).

The pinned llama.cpp v0.7.0 source applies explicit custom YaRN parameters to
context creation and adjusts the server training-context cap accordingly. Draft
context parameters inherit scaling. Downloaded metadata is not rewritten to
pretend the model was trained at the larger window. Verify native `/slots`
geometry and draft cache types before activation; leave disabled on any mismatch.
Later long-context retrieval/quality checks are required before removing the
provisional label. Until then use existing validated models for critical work.

## Reproduction and activation

`python -m arcB70.budget --write` regenerates the registry from pinned weights and
explicit formulas; `python -m shared.placements` regenerates UI/disabled client
snapshots. Allocation tests assert that each GPU slot count fits and one extra
does not, and the next 32k maximum-context step exceeds the budget.

All three OpenCode sources live in machine-setup, with `arcB70` disabled until
hardware, exact runtime, credentials and slot geometry are verified. The model
page and Prometheus show these as prepared profiles only. Follow
[hardware activation](hardware-transition-2026-10-23.md); bind the actual discrete
Arc and leave existing Intel iGPU translation/CPU/NPU services unchanged.
