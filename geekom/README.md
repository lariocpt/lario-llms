# Geekom — l-dev-ai

Halogen 0.18.19 serves Qwen3.8 Flash Next v2 through the existing Geekom owner
on `:11434/v1`. OpenCode offers **Halogen 128K** and **Halogen 256K**. These
choices share one resident model, four generation slots and a 524288-position
KV pool: four 128K requests, two 256K requests, or one 256K plus two 128K.

The administrator memlock fix is installed; 62.9 GiB of weights are confirmed
locked. Applications, Python and container layers live on btrfs. Only model
assets are under `/mnt/AI_Models/halogen/qwen38-flash-next` on XFS.
See [runtime setup, validation and memory limits](halogen/README.md).

The user retired normal Geekom Qwen, the older Flash GGUF and both Strata modes
on 2026-10-31. Their owner/OpenCode entries and three audited model roots were
removed, reclaiming 130.85 GiB. The Q3 model shared by the optional Radeon owner,
its other models, RTX Flash NVFP4 and the new B70 GPTQ setup were retained.
Earlier Vulkan/Strata evidence under `research/` is historical, not deployment
configuration. Archived registry fixtures under `tests/fixtures/` exercise
legacy routing/accounting only.

## Controls and validation

Use the model page at https://models.in.drlario.org or `geekom options`.
On/Off and model selection use the owner; no independent Halogen service or
second model should be started alongside the integrated-GPU backend.
`geekom start` starts cold, and durable Off survives reboot.

Four concurrent short requests, tool calls, cache reuse, complete SSE streaming,
cancellation/recovery and native vision passed. JSON-string tool arguments from
existing OpenCode histories are normalized by the same pinned Halogen parser
before token counting. A synthetic switched history matched the native token
count exactly. Existing conversation histories are not rewritten.

Short-context coding measured 89 tokens/s decode for one 256-token response;
four simultaneous responses measured 28–29 tokens/s each and about 108 output
tokens/s including request overhead. These are single-run observations, not
full-window throughput or retrieval validation.

Halogen, RTX Flash Next and B70 appear in the owner model pages and configured
profile metrics. Sanitized logs flow through the existing Alloy/Loki pipeline.
The Geekom collector's broken Loki WAL was archived under
`~/.local/state/lario-model-alloy-recovery/` and a fresh spool restored ingestion;
the archived spool was not deleted.

## Hardware and storage

GEEKOM A9 Mega, Ryzen AI Max+ 395 / Radeon 8060S, 128 GB unified memory;
Linux sees about 124 GiB, a 105.47 GiB GTT pool and a 512 MiB firmware carve-out.
The optional RX 7900 XT is a separate owner and placement. Keep its model files
and runtime independent of this integrated-GPU configuration.
