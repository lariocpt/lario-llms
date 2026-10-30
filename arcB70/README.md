# Arc B70: Qwen3.8 GPTQ INT4, vLLM XPU

The owner is bigcachy. The replacement uses the pinned GPTQ INT4 checkpoint,
patched four-token MTP, FP8 KV, native vision, and two concurrent sessions.
The owner validator measures the native KV pool and tests two equal windows;
`models.json` records the final per-session limit: **172,032 tokens (168K)**.
The public owner is active; concurrent text, native vision, tool calls and
streaming passed. Full-window retrieval remains pending after the user requested
immediate activation following native smoke. Two 256K windows do not fit
with the current runtime settings. Names have no provisional prefix.

`vllm/download.py` verifies model downloads, `vllm/validate.py --wait` checks
capacity/concurrency/vision/long retrieval, and `vllm/install.py --receipt PATH`
installs the validated owner. `shared/serving/vllm_gateway.py` checks native
scheduler occupancy, counts prompts with the native chat template, enforces
two-slot admission and retains authenticated owner controls. The engine listens
only on loopback behind the existing authenticated public endpoint, port 11437.

`shared/serving/sync_gpu_clients.py arcB70` replaces managed OpenCode choices on
bigcachy, l-dev-ai and mini-mobile without restarting workspaces. The plugin
preserves image pixels for this native vision profile. Reopen an idle workspace
to refresh settings after publication.

Docker software and compiled caches run from Btrfs. Model weights remain under
`/mnt/xfs/AI_Models/gptq/qwen38-27b-int4-asym`. Retired B70 Flash, Qwen GGUF,
Muse and draft weights were deleted at the user's explicit request, freeing
136.35 GiB. Historical SYCL measurements remain under `research/`.

Short 256-output-token public probes measured 87.5 tokens/s for one request and
76.8–78.5 tokens/s per request for two concurrent requests (including prefill).
These are short synthetic probes, not long-context throughput measurements.
