# app.py — the `intel` host's model backend: an OpenAI-compatible server over
# openvino_genai's LLMPipeline.
#
# STATUS 2026-10-04: WIP, NOT WIRED TO ANY SERVICE. The planned `intel` alias for
# Qwen3.8-Flash-Next is dead (qwen4exp cannot be loaded by openvino_genai at all —
# see GOTCHAS #13), and the intel host is being replanned. This server is the shape
# of what WILL serve a model OpenVINO can run (a converted dense model, NPU or CPU);
# it has never been brought up end-to-end. The generate(ChatHistory, cfg) and
# streamer-overload calls below are the C++ API shape, unverified against 2026.4.x.
#
# This is the UPSTREAM of the llama-swap instance in the intel-llm container
# (llama-swap fronts it on :8080, published at 127.0.0.1:11437, alias `intel`).
# llama-swap's proxy requires an OpenAI-compatible upstream, hence /v1/chat/completions
# and /v1/models. The old /generate + /chat/completions surface is gone — nothing
# called it (the compose service that shipped it referenced an image that does not
# exist on Docker Hub; see GOTCHAS #13).
#
# WHY openvino_genai AND NOT llama.cpp HERE: the NPU (PCI 00:0b.0, Core Ultra 200
# series) is only reachable through OpenVINO. The CPU path runs through the same
# pipeline, so one server covers the whole `intel` device matrix (CPU / NPU / GPU.0)
# and the benchmark (intel/benchmarks/benchmark.py) can probe all three without a
# second runtime.
#
# SINGLE-FLIGHT BY DESIGN: an openvino_genai LLMPipeline has no llama-server-style
# --parallel slot pool. generate() is serialized on GENERATE_LOCK, and the
# llama-swap entry carries concurrencyLimit: 1 — the second concurrent request gets
# the immediate retryable 429, the fleet-wide admission rule (GOTCHAS history:
# silence while queueing is indistinguishable from a dead provider).
#
# Device selection: OPENVINO_DEVICE (default CPU). The startup log line
# "visible devices:" is the answer to "does the system see the NPU?" — check
# `docker logs intel-llm` first when anything NPU-shaped misbehaves.
#
# Chat template: the C++ core applies the template embedded in the model to the
# ChatHistory — that is the design; the call path itself is UNVERIFIED (see the
# STATUS block above). What WAS verified on the qwen4exp GGUF (2026-10-04, host
# python, openvino_genai 2026.2.1): the standalone Tokenizer(gguf) class fails
# (gguf_tensor_to_f16), and so does LLMPipeline(gguf) — the arch is unsupported,
# not a tokenizer detail.

import os
import queue
import threading
import time
import uuid

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

from openvino import Core
from openvino_genai import ChatHistory, GenerationConfig, LLMPipeline

DEVICE = os.getenv("OPENVINO_DEVICE", "CPU")
MODEL_PATH = os.getenv(
    "MODEL_PATH",
    "/models/gguf/qwen38-flash/Qwen3.8-Flash-Next-UD-Q3_K_XL-00001-of-00003.gguf",
)
MODEL_ID = os.getenv("MODEL_ID", "intel")

# Sampling — the block the XT entry ran with (moved from agent-model.sh's
# QWEN38F_SAMPLING on 2026-10-04): Qwen3.8 thinking mode, vendor-recommended.
DEFAULT_TEMP = float(os.getenv("SAMPLE_TEMP", "1.0"))
DEFAULT_TOP_P = float(os.getenv("SAMPLE_TOP_P", "0.95"))
DEFAULT_TOP_K = int(os.getenv("SAMPLE_TOP_K", "20"))
DEFAULT_MIN_P = float(os.getenv("SAMPLE_MIN_P", "0.0"))

app = FastAPI(title="intel-llm (OpenVINO GenAI)", version="1.0.0")

pipe = None
ready = threading.Event()
load_error: Optional[BaseException] = None
GENERATE_LOCK = threading.Lock()


class ChatMessage(BaseModel):
    role: str
    content: Optional[str] = None
    name: Optional[str] = None
    tool_calls: Optional[list] = None


class ChatCompletionRequest(BaseModel):
    model: Optional[str] = None
    messages: list[ChatMessage]
    max_tokens: int = 2048
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    min_p: Optional[float] = None
    stream: bool = False
    stop: Optional[list[str] | str] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None


def _visible_devices() -> list:
    try:
        return Core().available_devices
    except Exception as e:  # device enumeration must never kill the server
        return [f"(enumeration failed: {e})"]


def _build_pipeline():
    global pipe, load_error
    t0 = time.time()
    print(f"[intel-llm] visible devices: {_visible_devices()}", flush=True)
    print(f"[intel-llm] loading {MODEL_PATH} on {DEVICE} ...", flush=True)
    try:
        pipe = LLMPipeline(MODEL_PATH, device=DEVICE)
        ready.set()
        print(f"[intel-llm] pipeline ready on {DEVICE} in {time.time() - t0:.1f}s", flush=True)
    except Exception as e:
        load_error = e
        ready.set()  # unblock /health so the failure is reported, not silent
        print(f"[intel-llm] PIPELINE LOAD FAILED: {e!r}", flush=True)
        # Exit non-zero: `restart: unless-stopped` retries after a reboot when a
        # device node was still coming up; a persistent load error will flap loudly
        # in `docker logs` rather than serving 503s forever.
        raise SystemExit(3) from e


@app.on_event("startup")
async def _startup():
    threading.Thread(target=_build_pipeline, daemon=True).start()


def _config_from(req: ChatCompletionRequest) -> GenerationConfig:
    cfg = GenerationConfig()
    cfg.max_new_tokens = req.max_tokens
    temp = req.temperature if req.temperature is not None else DEFAULT_TEMP
    cfg.do_sample = temp > 0
    cfg.temperature = temp
    cfg.top_p = req.top_p if req.top_p is not None else DEFAULT_TOP_P
    cfg.top_k = req.top_k if req.top_k is not None else DEFAULT_TOP_K
    cfg.min_p = req.min_p if req.min_p is not None else DEFAULT_MIN_P
    if req.presence_penalty is not None:
        cfg.presence_penalty = req.presence_penalty
    if req.frequency_penalty is not None:
        cfg.frequency_penalty = req.frequency_penalty
    if req.stop:
        cfg.stop_strings = req.stop if isinstance(req.stop, list) else [req.stop]
    return cfg


def _history_from(req: ChatCompletionRequest) -> ChatHistory:
    h = ChatHistory()
    for m in req.messages:
        h.append(m.role, m.content or "")
    return h


def _require_ready():
    if load_error is not None:
        raise HTTPException(status_code=500, detail=f"pipeline load failed: {load_error!r}")
    if pipe is None:
        raise HTTPException(status_code=503, detail="pipeline loading")


@app.get("/health")
async def health():
    _require_ready()
    return {"status": "healthy", "device": DEVICE, "model_id": MODEL_ID}


@app.get("/v1/models")
async def models():
    return {
        "object": "list",
        "data": [{"id": MODEL_ID, "object": "model", "owned_by": "intel-llm"}],
    }


def _chunk(cid: str, created: int, role: Optional[str], delta_content: Optional[str],
           finish: Optional[str]) -> str:
    import json
    delta = {}
    if role is not None:
        delta["role"] = role
    if delta_content is not None:
        delta["content"] = delta_content
    choice = {
        "index": 0,
        "delta": delta,
        "finish_reason": finish,
    }
    return "data: " + json.dumps(
        {
            "id": cid,
            "object": "chat.completion.chunk",
            "created": created,
            "model": MODEL_ID,
            "choices": [choice],
        }
    ) + "\n\n"


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest):
    _require_ready()
    cfg = _config_from(req)
    history = _history_from(req)
    cid = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())

    if not req.stream:
        t0 = time.time()
        with GENERATE_LOCK:
            text = pipe.generate(history, cfg)
        elapsed = time.time() - t0
        prompt_chars = sum(len(m.content or "") for m in req.messages)
        print(
            f"[intel-llm] completion {cid[:12]}: {len(text)} chars out, "
            f"{prompt_chars} chars in, {elapsed:.1f}s",
            flush=True,
        )
        return {
            "id": cid,
            "object": "chat.completion",
            "created": created,
            "model": MODEL_ID,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": -1,  # char counts are the honest figure pre-tokenizer;
                "completion_tokens": -1,  # the C++ core does not expose token counts
                "total_tokens": -1,  # through the python binding (verified 2026-10-04)
            },
        }

    # Streaming: the C++ TextStreamer pushes decoded tokens into a queue as they
    # are generated; the SSE generator drains it. Generation still holds
    # GENERATE_LOCK, so at most one stream at a time (concurrencyLimit: 1 upstream).
    sink: "queue.Queue" = queue.Queue()

    def _on_token(tok: str):
        sink.put(tok)

    def _run():
        try:
            with GENERATE_LOCK:
                pipe.generate(history, cfg, _on_token)
        finally:
            sink.put(None)

    threading.Thread(target=_run, daemon=True).start()

    def _sse():
        yield _chunk(cid, created, role="assistant", delta_content=None, finish=None)
        while True:
            tok = sink.get()
            if tok is None:
                break
            if tok:
                yield _chunk(cid, created, role=None, delta_content=tok, finish=None)
        yield _chunk(cid, created, role=None, delta_content=None, finish="stop")
        yield "data: [DONE]\n\n"

    return StreamingResponse(_sse(), media_type="text/event-stream")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8082)
