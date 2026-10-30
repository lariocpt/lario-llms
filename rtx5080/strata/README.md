# RTX 5080 CUDA Strata

Qwen3.8 Flash Next NVFP4 GPTQ, one **131,072-token (128K) session**, Q4 KV and
native vision. The user authorized reducing the original 256K target to enable
vision. The 128K configuration passed native allocation, text, red/blue image,
function-call and streaming checks. Full-window retrieval quality is not yet
validated. Names have no provisional prefix.

The short 256-output-token native probe measured 30.8 tokens/s including prompt
processing, about 33 tokens/s during generation, with a 0.64s first token.
Those are short synthetic measurements, not long-context speeds.

Pinned Terminal and signed CUDA engine 0.1.54 (release v0.2.8) run from `~/strata`
on Btrfs. Model weights and the matching BF16 image encoder live directly on XFS:
`/mnt/xfs/AI_Models/strata/models/qwen38-flash-next-nvfp4-gptq`.
`weights.json` and `vision_weights.json` pin URLs, sizes and checksums. Downloads
are complete and verified; the completed download service is no longer enabled
at boot, avoiding an unnecessary 130GB checksum scan on each restart.

The engine uses the verified RTX UUID, W4A8 prefill, no expert skipping and an
automatic GPU expert cache with a 2GiB reserve. About 60GiB of experts are pinned
in system RAM; the PLE table uses its direct SSD reader. Initial loading can
create memory pressure while caches are reclaimed. Native inference observed
zero file-tier expert reads after loading. B70 remains a separate live owner.

`validate.py` borrows only an idle, enabled RTX and restores its prior profile
and operator policy. `install.py --receipt PATH` checks the native command,
preserves keys, updates the registry-derived backend config and activates the
validated profile. The same exclusive group retains manual describe/OCR
alternatives. Image generation remains a manually selected exclusive workload;
image/design MCPs use the Radeon and never automatically evict RTX Flash Next.

`shared/serving/sync_gpu_clients.py rtx5080` publishes source choices and renders
OpenCode on all three machines without restarting active workspaces. The plugin
preserves raw images for this native vision profile. Reopen an idle workspace to
refresh its model list.
