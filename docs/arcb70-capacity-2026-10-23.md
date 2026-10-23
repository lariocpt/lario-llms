# Arc B70 Qwen3.8 capacity preparation — 2026-10-23

These are memory estimates and disabled configurations, not tested B70 capacity.
Assume a full 32 GiB reported by the driver and retain **3.5 GiB** for recurrent
state, compute buffers, driver allocations and other overhead. Verify the actual
board/driver budget and all allocations after installation. Larger prompt batches
or other GPU users may require more headroom and smaller contexts.

## Weight and KV choices

Use the same dense Qwen3.8-27B model family. **Arc Smart Q6 uses UD-Q6_K**, 21,983,677,344
bytes (20.47 GiB), rather than Geekom Smart's Q8_K_XL (29.30 GiB). **Arc Medium
uses UD-Q4_K_XL**, 17,559,178,144 bytes (16.35 GiB). Both are quantized weights;
Smart Q4 shares Medium’s Q4 weights but requests xhigh reasoning; Medium
requests medium reasoning. Geekom is unchanged. Smart Q4 and Q6 are separate
fixed choices. Q4 GPU KV gives the calculated 128k capacity of five Smart Q4
slots or three Smart Q6 slots; 256k has two Smart Q4 slots or one Smart Q6 slot.
These counts share an unverified 3.5 GiB reserve, including concurrent recurrent
state and buffers; actual runtime may require fewer slots. Q4 KV reduces
precision compared with the earlier one-slot 128k Smart Q6 Q8-KV candidate.

Sizes and SHA256 values were read from Hugging Face's model API at pinned revision
4ca720788d1e01f1bff70c033e0d0028fd02e502. The candidates store those immutable
revision/checksum/byte details; downloading weights is not part of preparation.
[Publisher files](https://huggingface.co/unsloth/Qwen3.8-27B-GGUF/tree/4ca720788d1e01f1bff70c033e0d0028fd02e502).

Reuse the conservative installed-GGUF attention estimate: 17 full-attention
layers, 4 KV heads, 256 key plus 256 value dimensions. Q8_0 stores 34/32 bytes per
value, Q4_0 18/32. Attention bytes = context × slots × 17 × 4 × 512 × type size.
This intentionally excludes recurrent state and buffers, covered only by the
unverified reserve. See [the existing GGUF-derived calculation](geekom-q8-slot-budget-2026-10-17.md).

## Candidate profiles

| Profile | Server context | Slots | KV | Weights + GPU KV | With 3.5 GiB reserve | RAM KV |
| --- | ---: | ---: | --- | ---: | ---: | ---: |
| qwen3.8-smart-128k | 128k | 3 | q4_0 GPU | 27.65 GiB | 31.15 GiB | 0.00 GiB |
| qwen3.8-smart-256k | 256k | 1 | q4_0 GPU | 25.26 GiB | 28.76 GiB | 0.00 GiB |
| qwen3.8-smart-416k | 416k | 1 | q4_0 GPU | 28.24 GiB | 31.74 GiB | 0.00 GiB |
| qwen3.8-smart-512k-ram-kv | 512k | 2 | q8_0 CPU | 20.47 GiB | 23.97 GiB | 36.12 GiB |
| qwen3.8-medium-128k | 128k | 2 | q8_0 GPU | 25.38 GiB | 28.88 GiB | 0.00 GiB |
| qwen3.8-medium-256k | 256k | 1 | q8_0 GPU | 25.38 GiB | 28.88 GiB | 0.00 GiB |
| qwen3.8-medium-512k | 512k | 1 | q4_0 GPU | 25.92 GiB | 29.42 GiB | 0.00 GiB |
| qwen3.8-medium-640k | 640k | 1 | q4_0 GPU | 28.31 GiB | 31.81 GiB | 0.00 GiB |
| qwen3.8-medium-512k-ram-kv | 512k | 2 | q8_0 CPU | 16.35 GiB | 19.85 GiB | 36.12 GiB |
| qwen3.8-smart-q4-128k | 128k | 5 | q4_0 GPU | 28.31 GiB | 31.81 GiB | 0.00 GiB |
| qwen3.8-smart-q4-256k | 256k | 2 | q4_0 GPU | 25.92 GiB | 29.42 GiB | 0.00 GiB |
| qwen3.8-smart-q4-512k | 512k | 1 | q4_0 GPU | 25.92 GiB | 29.42 GiB | 0.00 GiB |
| qwen3.8-smart-q4-640k | 640k | 1 | q4_0 GPU | 28.31 GiB | 31.81 GiB | 0.00 GiB |
| qwen3.8-smart-q4-512k-ram-kv | 512k | 2 | q8_0 CPU | 16.35 GiB | 19.85 GiB | 36.12 GiB |

128k and 256k mean 131072 and 262144 server tokens exactly. Client context is
server minus 4096, preserving output headroom according to the existing fleet
contract. Each option exclusively owns this GPU; slots are simultaneous requests
on that one loaded profile, not simultaneous different models.

## Maximum context and 512k concurrency

**Native context remains 256k.** 416k Smart Q6 and 640k Smart Q4 / Medium Q4 are calculated GPU-only
maximum candidates rounded down to 32k steps under this reserve, using Q4 K/V.
They use explicit YaRN 1.625 and 2.5 with original context 262144. This is a
memory-budget maximum under these assumptions, not a model-supported quality
claim or a guaranteed allocation. Extended-context quality requires later checks.
The immediately larger 448k Smart / 672k Medium allocations exceed this reserve.

The standard 512k Medium single-slot candidate uses Q4 KV (9.56 GiB), leaving
about 6.08 GiB before runtime overhead. Smart Q6 at 512k GPU Q4 KV leaves only
1.96 GiB, below the selected reserve, so that GPU-only profile is omitted.

Two GPU-resident 512k Q4-KV slots require 19.125 GiB attention cache alone:
35.48 GiB with Medium weights or 39.60 GiB with Smart Q6, before any runtime
reserve. **Neither fits entirely in 32 GiB VRAM.** Existing Geekom Smart Q8
cannot safely fit even 128k GPU KV with the selected reserve.

The three explicit **512k / 2 slots / RAM KV** candidates use `--no-kv-offload`
and Q8 K/V, requiring an estimated 36.125 GiB attention cache in **system RAM**.
Their weights remain offloaded to Arc. They are expected to be slower because
attention runs on CPU with transfers; no speed is promised. Bigcachy currently
reports about 125 GiB total RAM, but available RAM must be checked at activation.
The 3.5 GiB reserve does not cover that host RAM; also budget host recurrent/
compute allocations and the other services. Never silently change a GPU profile
to RAM KV; each has a separate ID and visible label.

## Software and activation

Prefer a pinned llama.cpp SYCL build for the first Arc-specific probe. Current
upstream documents quantized-cache flash attention and Intel XMX acceleration:
[official SYCL backend](https://github.com/ggml-org/llama.cpp/blob/master/docs/backend/SYCL.md).
Q4 K/V, hybrid recurrent state, CPU-KV and long-context allocation must all be
verified on the exact chosen build and B70 driver. Vulkan remains an alternative
if it works better. No backend is certified by reading its documentation.

The staged registry uses a dedicated future binary path, bounded 1024/256 prompt
batches, explicit quantized K/V and YaRN above native context. Its pinned device
selector must be supplied during provisioning after detecting the card; do not
run the generated backend with an unbound generic Intel GPU selection. Never
let it capture the existing iGPU or NVIDIA card. Any changed serving arguments
must trigger catalogue regeneration because IDs include them.

Machine-setup shared/agents/opencode.prepared.json contains the exported disabled
provider for all three dev machines. OpenCode's documented disabled_providers
prevents the entries appearing in its selector before activation:
[OpenCode configuration](https://opencode.ai/docs/config/#disabled-providers).
The model page and Grafana show them now as **prepared**, with no capacity or
readiness claim. After installation, verify a short response and native slot
geometry, then provision credentials and remove the explicit disable in source.
This work does not restart any inference service or perform benchmarking.
