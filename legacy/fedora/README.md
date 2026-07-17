# legacy/fedora — retired Fedora-era stack. DO NOT RUN.

Quarantined 2026-07-17 during the CachyOS migration cleanup.

**`scripts/setup-llama-swap-fedora.sh` is dangerous:** it regenerates the OLD
`/mnt/Shared`-pathed systemd unit and will clobber the live native llama-swap
service (which uses `~/Projects/personal/lario-llms/...` paths). It has been
chmod -x for that reason.

Also here:
- `docker-compose.fedora-native.yml` — Fedora topology, superseded by `docker-compose.cachyos.yml`
- `docker-compose.override.yml` — auto-merge GPU spoof for the retired `llamacpp`
  container. Moved out of the repo root ON PURPOSE so a bare `docker compose up`
  no longer silently merges it. The live invocation uses explicit `-f` flags.
- `llama-cpp/{Dockerfile,llama,build.sh,setup-models.sh,swap-config.sh}` — the retired
  containerized backend and its helpers
- `llama-cpp/config-fast.yaml`, `config-max.yaml` — old profile configs, replaced by
  the generated `llama-cpp/config.yaml` + `main-model.sh` toggle
- `docs/strix_halo_fedora_setup.md` — Fedora host GPU setup

Current setup lives in the repo root README and `~/Projects/personal/machine-setup`.
