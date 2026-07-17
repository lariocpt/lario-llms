# <agent-name> (Nanoclaw)

One-line description.

## Files
- `CLAUDE.local.md` — agent identity & standing instructions (becomes the group's local memory).
- `container.json` — provider (`opencode`), model (`qwen3-coder:30b`), mounts, packages, skills.
- `mission.md` — the work this agent owns.
- `clone.manifest.txt` — repos to clone into `workspace/` (its own clone).
- `.env.example` — copy to `.env` and add the Discord bot token.
- `workspace/` — gitignored cloned repos.

## Deploy
```bash
cp .env.example .env
../../deploy/clone-repos.sh <agent-name>
../../deploy/deploy-nanoclaw.sh <agent-name>   # syncs to ~/nanoclaw/groups, creates the group
```
`deploy-nanoclaw.sh` stamps the `__AGENT_DIR__`/`__HOME__`/`__GROUP_NAME__` placeholders in
`container.json` to absolute values when it materialises the group.
