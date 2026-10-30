# GPU serving migration — 2026-10-30

## Active and verified

The B70 replacement targets vLLM XPU, GPTQ INT4, four-token patched MTP,
FP8 KV, native vision and two equal sessions. Native capacity is below two
256K windows; the final limit is established by re-profiling and concurrent
near-full retrieval. Owner integration and machine-setup model sources now use
one immutable replacement entry without a provisional prefix. The active owner has two 172,032-token (168K) sessions. Publication followed
concurrent text, vision, tools and streaming smoke checks, as explicitly requested
by the user before the long test. Full-window retrieval remains pending.
Public short probes measured 87.5 tokens/s single and 76.8–78.5 tokens/s per
request with two concurrent requests. All three OpenCode CLIs expose only this
new B70 entry.

The previous SYCL Q4 profile completed a 516,171-token synthetic retrieval
check, with about 23 tokens/s short decode and 2.58 tokens/s near full context.
Those historical measurements do not describe the new vLLM configuration.

Mini-mobile's `gdp7900xt` retains its three chat profiles and adds describe/OCR.
Both vision profiles passed the red/blue image fixture. A real MCP description
borrowed the idle Radeon and restored the captured Qwen chat profile. Busy
hardware was also correctly refused. Small requests may fall back to a 3060 Ti;
there is no automatic RTX fallback. The OpenCode hook preserves raw pixels for
the native B70 vision profile instead of delegating them.

RTX Qwen Image and FLUX Klein both generated valid 512px PNGs using the relocated
Btrfs runtime and restored cold serving. Their whole-job times were about 61
and 44 seconds respectively, for different step counts (8 and 4), so this is not
a comparative model benchmark. Both remain manually selected alternatives.

## Storage

Executable runtimes live on Btrfs: `~/strata`, native B70/MKL and admission under
`~/.local/share/lario-model-runtimes`, and each image owner's isolated ComfyUI
installation under that directory. The Radeon container graph and llama-swap
binary were also relocated to home. Native process-map checks found no XFS
executable mappings in the active B70/RTX backend and gateway units. CUDA,
Triton and TorchInductor compiled caches stay under home.

Weights, download caches, input/output images and control data remain on XFS.
The model download uses direct files and resumable partials, without a duplicate
Hugging Face cache. Existing XFS runtime copies are not used by these launchers.

## Still pending

- RTX Flash Next is now active with one 128K Q4-KV vision session, original
  NVFP4 GPTQ weights, and the pinned BF16 image encoder. Native and public text,
  red/blue vision, forced function calls and streaming passed. The public short
  probe measured 30.3 tokens/s including prompt processing and 0.67s first token.
  Executable map inspection found no XFS executable mappings. The user authorized
  reducing context for vision; full-window retrieval remains untested. Describe
  and OCR remain manually selected exclusive alternatives.
- Mini-mobile's ROCm PyTorch runtime is still downloading. Radeon model weights
  finished copying from bigcachy. Validate Qwen Image, FLUX Klein and upscaling
  on the Radeon before declaring generation ready; the installer/controller
  already target Btrfs and select the physical Radeon UUID.
- The user subsequently authorized immediate deletion of the B70 Flash GGUF,
  normal Qwen Q4 GGUF, Muse and draft weights. They were deleted after pausing
  admission and stopping the idle backend, freeing 136.35 GiB. Validation retains
  the retirement pause until the replacement owner is installed.

Background units: `gpu-migration-download`, `gpu-migration-rocm-home-install`.
Logs are in the user journal and `~/.local/state/gpu-migration/`.

## Validation and sources

B70 regeneration is idempotent and emits only its one active profile.
`arcB70/vllm/install.py` gates activation on matching native evidence;
`shared/serving/sync_gpu_clients.py` replaces managed model choices and renders
all clients while preserving unrelated settings. Hardware registries remain the
source of generated backend YAML.

New admission, profile rendering, routing, restoration, storage and attachment
checks pass. The broad Python suite ran 304 tests: three existing Geekom preset
assertions in `tests/test_presets.py` still fail and one test is skipped. The
Geekom registry, modelctl and those preset tests were unchanged by this work.
The MCP suite passes all 22 tests, attachment/plugin checks pass all 14 tests,
and machine-setup dry runs pass for bigcachy, l-dev-ai and mini-mobile.

Existing unrelated local MCP-readiness changes and research files were retained.
No live user request was cancelled; only this migration's own long test was
stopped and restarted when the requested activation order changed.
