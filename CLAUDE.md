# lario-llms — agent notes

- Hardware registries are `geekom/models.json`, `7900xt/models.json`, and `rtx5080/models.json`; `shared/modelctl.py` generates runtime YAML. Never hand-edit generated configs.
- Select with the hardware command on its owner: Geekom on l-dev-ai; Radeon/RTX on bigcachy. `main-model` and `agent-model` are compatibility wrappers.
- `-c` is slots × per-slot context; concurrencyLimit equals slots. Fleet capacity comes from the ready model and subtracts reserved slots; failure means zero capacity.
- All weights and model-download caches belong on XFS: /mnt/AI_Models (l-dev-ai), /mnt/xfs/AI_Models (bigcachy).
- Geekom is native Vulkan; Radeon is ROCm in agent-llm; RTX is native CUDA with a vision DNS proxy. Intel is native OpenVINO GenAI with pinned matching Runtime/tokenizer ABI.
- RAG must keep BAAI/bge-m3, CLS pooling, L2 normalization, 1024 dimensions and 8192-token input. Do not replace the embedding space because a different model has the same dimension.
- Client sources belong in ../machine-setup; Hermes sources in ../agents. Never copy live agent databases/directories or edit generated config.yaml; use their deploy and backup scripts.
- legacy/, attic/, docs/history/ are historical. Use start_all.sh or explicit bigcachy+intel compose files, never a generic compose up.
- Avoid unnecessary model restarts: they unload weights. Model selectors never restart OpenCode. See docs/OPENCODE.md for the accidental home-repository indexing outage.
