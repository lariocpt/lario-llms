# <agent-name> (Hermes)

One-line description of what this agent is for.

## Files
- `config.yaml` — model (→ Bifrost/Qwen), Discord, memory, skills. Mounted as `<HERMES_HOME>/config.yaml`.
- `SOUL.md` — persona / standing instructions (loaded fresh each message).
- `mission.md` — the work this agent owns.
- `.env.example` — copy to `.env` and add the Discord bot token.
- `clone.manifest.txt` — repos to clone into `workspace/` (its own clone).
- `ingest.manifest.yaml` — knowledge sources to push into ChromaDB.
- `skills/` — custom skills. `knowledge/` — seed documents.
- `memory/`, `workspace/` — gitignored runtime state.

## Run
```bash
cp .env.example .env          # add Discord token
../../deploy/clone-repos.sh <agent-name>
../../deploy/ingest-knowledge.sh <agent-name>
docker compose up -d hermes-<agent-name>
docker logs -f hermes-<agent-name>     # expect "Discord Gateway connected"
```
