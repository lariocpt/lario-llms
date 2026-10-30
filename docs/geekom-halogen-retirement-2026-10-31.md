# Geekom Halogen cutover and retirement — 2026-10-31

The live Geekom owner and managed OpenCode sources now retain only Halogen v2
128K/256K profiles. Existing immutable Halogen IDs were preserved. Default and
agent pins referencing retired Geekom entries were moved to Halogen 128K; RTX,
B70 and optional Radeon model configurations were retained. Active inference
was allowed to finish before the Geekom owner catalog was reloaded.

The explicit three-root audit removed old Flash Q3 GGUF shards, the Q4/Q8
Geekom Hugging Face repository, and the derived Strata pack: 130.8503 GiB of
allocated files. All referenced retained models were verified. The Radeon's
shared normal Qwen Q3, Muse and vision files remain. No other host's weights
were deleted. `scripts/retire_geekom_qwen.py` contains the bounded deletion
allowlist, mount, live-catalog, protected-file and process-map checks.

The model-switch failure in the identified OpenCode conversation was reproduced
with JSON-string tool arguments. The adapter now uses the exact normalizer from
the pinned Halogen image before template rendering. The synthetic switched
history passed inference and both counters agreed on 103 input tokens. The
conversation itself was not edited. Compaction output limits remain a separate
client/output-budget concern.

Halogen, RTX Flash NVFP4 and B70 GPTQ INT4 are present in the model-control
owner catalogs, configured-profile gauges and central Prometheus. Loki contains
hardware-labelled operational streams for all three. B70's vLLM unit was added
to the journal allowlist. Geekom's non-sequential Loki WAL was archived intact
under `~/.local/state/lario-model-alloy-recovery/20261031T012132/loki-wal` and a
fresh spool restored collection. Historical archived WAL records are preserved
for recovery, not claimed to have been replayed.

Obsolete stopped containers deleted: bigcachy's `agent-llm` (llama.cpp ROCm),
and l-dev-ai's never-started CUDA `vision` container. Neither host had an old
Strata container. bigcachy has no rootless Podman installation; l-dev-ai's
rootless Podman inventory retained only the active Halogen container. Active
B70 vLLM, native RTX Strata, optional Radeon and unrelated containers remain.

Validation: 315 Python tests passed with one existing skip; 15 OpenCode plugin
tests passed; 37 machine-setup tests and all three provisioning dry runs passed.
The old registry snapshots in `tests/fixtures` are regression inputs for generic
legacy accounting/routing; they are not published model choices. Live evidence
is under `research/benchmarks/20261031-geekom-halogen/`.
