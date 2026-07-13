#!/usr/bin/env python3
"""smart-router: OpenAI-compatible sidecar with DETERMINISTIC routing.

Launched by llama-swap as the `smart` model entry. Routing is intentionally simple and
reliable (no embeddings — the semantic version caused misroutes and model-swap thrash):

  * any message carrying an image content part            -> "qwen3-vl"  (always resident)
  * everything else                                       -> the current TEXT TARGET

The text target is read from `text-target.txt` (next to this file) on EVERY request, so
`smart-use.sh minimax|mistral` can change it live with no router restart and no llama-swap
reload. Default is "minimax".

Because qwen3-vl is a small, always-resident model (llama-swap `always` group) and the
default text target (minimax) is also resident, normal operation never triggers a big-model
swap. The only swap happens when you deliberately flip the text target to mistral.
"""

import argparse
import logging
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

log = logging.getLogger("smart-router")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

UPSTREAM = "http://127.0.0.1:11434"          # llama-swap itself
VISION_TARGET = "qwen3-vl"                    # always-resident vision model
TARGET_FILE = Path(__file__).parent / "text-target.txt"
DEFAULT_TEXT_TARGET = "minimax"
ALLOWED_TEXT_TARGETS = {"minimax", "mistral"}

app = FastAPI()


def text_target() -> str:
    """Read the current text target fresh each request (live-switchable)."""
    try:
        t = TARGET_FILE.read_text().strip()
        if t in ALLOWED_TEXT_TARGETS:
            return t
        log.warning("text-target.txt = %r not in %s; using default", t, ALLOWED_TEXT_TARGETS)
    except FileNotFoundError:
        pass
    return DEFAULT_TEXT_TARGET


def has_image(messages: list) -> bool:
    for m in messages:
        content = m.get("content")
        if isinstance(content, list) and any(
            p.get("type") in ("image_url", "input_image", "image") for p in content
        ):
            return True
    return False


def pick_route(body: dict) -> str:
    messages = body.get("messages", [])
    if has_image(messages):
        return VISION_TARGET
    return text_target()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "vision": VISION_TARGET, "text_target": text_target()}


@app.get("/v1/models")
def models() -> dict:
    return {"object": "list", "data": [{"id": "smart", "object": "model", "owned_by": "smart-router"}]}


@app.post("/v1/chat/completions")
async def chat(request: Request) -> Response:
    body = await request.json()
    route = pick_route(body)
    body["model"] = route
    log.info("routed -> %-9s (image=%s)", route, has_image(body.get("messages", [])))

    if body.get("stream"):
        async def relay():
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("POST", f"{UPSTREAM}/v1/chat/completions", json=body) as up:
                    async for chunk in up.aiter_bytes():
                        yield chunk
        return StreamingResponse(relay(), media_type="text/event-stream")

    async with httpx.AsyncClient(timeout=None) as client:
        r = await client.post(f"{UPSTREAM}/v1/chat/completions", json=body)
    return JSONResponse(r.json(), status_code=r.status_code)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True, help="port llama-swap assigned (${PORT})")
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
