# smart-router — deterministic role router (native)

An OpenAI-compatible sidecar that llama-swap runs as the `smart` model entry. Routing is
**deterministic** — no embeddings (the semantic version misrouted and thrashed model swaps):

- a request carrying an **image** → `qwen3-vl` (small, always-resident vision model)
- everything else → the current **text target** (`minimax` by default, or `mistral`)

The text target lives in `text-target.txt` and is read on every request, so you can flip it
live with **`../smart-use.sh minimax|mistral`** — no router restart, no llama-swap reload.

## Why this never thrashes
`qwen3-vl` (~6GB) and the default text target `minimax` (~94GB) are **both resident**
(llama-swap `always` + `big` groups), so normal text/vision traffic never triggers a swap.
The single, deliberate swap only happens when you run `smart-use.sh mistral` (unloads MiniMax,
loads Mistral). Images still hit the resident Qwen3-VL instantly.

## Install / run
It's wired as the `smart` entry in `../llama-cpp/config.yaml`:
```yaml
  "smart":
    cmd: |
      /mnt/Shared/personal/lario-llms/smart-router/.venv/bin/python
      /mnt/Shared/personal/lario-llms/smart-router/router.py --port ${PORT}
    checkEndpoint: /health
    ttl: 0
```
Deps (already in `.venv`): `fastapi uvicorn httpx`. Recreate with:
`uv venv --python 3.12 && uv pip install fastapi uvicorn httpx`.

> The old embedding router (`bge-m3` + `role-exemplars.yaml`) is retired. Do not re-enable it.
