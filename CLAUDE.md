# lario-llms — agent notes

- TWO model endpoints (since 2026-08-23): l-dev-ai `:11434` = coding `main`
  (qwen3.8); bigcachy `:11436` = the agents' `agent-llm` container (RX 7900 XT,
  Muse Glimmer, alias `agent`).
- BOTH llama-swap configs are GENERATED and gitignored: `llama-cpp/config.yaml` by
  `main-model.sh` (l-dev-ai), `llama-cpp/agent-config.yaml` by `agent-model.sh`
  (bigcachy). Never hand-edit either; switch via `main-model <name>` /
  `agent-model <name>` (the latter does the `docker restart agent-llm` itself).
  Fresh clone on bigcachy: `./agent-model.sh config muse-glimmer` before `up`, or
  llama-swap fails with "config not found".
- On l-dev-ai the backend is NATIVE llama-swap on `:11434` (systemd user unit) —
  there is no llamacpp container anymore. Never start the `llamacpp` compose service.
- Compose invocation requires BOTH `-f` flags (they exclude the retired override):
  `docker compose -f docker-compose.yml -f docker-compose.cachyos.yml up -d bifrost chromadb rag_api ml_pipeline`
  On bigcachy use `-f docker-compose.bigcachy.yml` instead of cachyos; `agent-llm`
  additionally needs the `xt` profile + `XT_RENDER_NODE`/`AGENT_LLM_BIND_*` from `.env`.
- `legacy/fedora/` = DO NOT RUN (regenerates the dead /mnt/Shared unit).
  `attic/` = stale-path one-offs, reference only.
- `bifrost/` + `chroma-data/` are live docker bind mounts, gitignored by design.
- Bifrost tailnet bind comes from `.env` (`BIFROST_BIND_IP`); admin API has no auth.
- Avoid restarting llama-swap casually — it unloads the resident ~87 G model.
- Machine provisioning (mounts/kargs/unit/backups): `~/Projects/personal/machine-setup`.
