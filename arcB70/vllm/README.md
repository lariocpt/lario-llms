# B70 vLLM XPU replacement candidate

Requested target: Qwen3.8-27B GPTQ INT4, patched MTP, vision, **two 256K slots**.
If that does not fit, the user authorizes the largest validated equal context
for two concurrent slots. Never advertise two full windows merely because
`max-num-seqs=2` starts successfully.

The pinned stock asymmetric GPTQ checkpoint and newer B70 patched vLLM image are
recorded in `manifest.json`. Weights download directly to XFS; Docker software
runs from the existing Btrfs `/var/lib/docker` store, and compiled caches stay
under home. The patch set includes the BF16 MTP path and packed verification.

`download.py` downloads and checksum-checks the checkpoint. `prepare.py` prints
the isolated candidate command after prerequisites are present. `validate.py
--wait` waits for downloads and an idle, unpaused B70, takes its hardware lock,
closes admission, and temporarily stops the current backend. It checks actual
native KV capacity, concurrent short requests, vision, and two simultaneous
near-full retrieval prompts. If needed it restarts with the measured smaller
per-request ceiling before those tests. It restores the captured working profile when one still exists; the explicit
retirement lease otherwise remains paused. It does not publish a new menu entry.

Evidence and detailed startup logs go to `~/.local/state/gpu-migration/`.
Current background units: `gpu-migration-vllm-weights`,
`gpu-migration-vllm-runtime`, and `gpu-migration-vllm-validation`.

The old one-slot llama.cpp profile has been retired and its weights deleted. Serving integration must preserve the measured two-slot admission
limits, native vision, streaming, tools and authenticated owner controls.

## Replacement owner

The retired GGUF weights have now been deleted at the user's explicit request.
A retirement policy receipt lets validation borrow the deliberately paused owner
without restoring a deleted profile. A subsequent operator policy change blocks
that automatic transition. The validator re-profiles after reducing context and
adjusts downward until the final native pool holds both advertised windows.

`install.py --receipt PATH` requires the completed validation receipt, preserves
credentials, disables the old SYCL unit and installs `lario-b70-vllm.service`.
`run.py` derives the served immutable identity and context from `models.json`.
The authenticated gateway uses native model metadata, scheduler metrics and
native chat-template tokenization. It preserves Off/pause/cancellation controls
and returns overload errors instead of silently queueing extra sessions.

The owner is now active with two 168K sessions after the user explicitly requested
activation following native smoke. Full-window retrieval is pending.
