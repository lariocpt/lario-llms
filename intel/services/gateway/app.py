#!/usr/bin/env python3
"""
Intel AI Gateway - Unified API for all Intel services
Routes requests to embedding, ASR, translation, TTS services
"""

import os
import httpx
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import uvicorn

app = FastAPI(
    title="Intel AI Gateway",
    version="1.0.0",
    description="Unified API for Intel NPU/iGPU AI services",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Service URLs
EMBEDDING_URL = os.getenv("EMBEDDING_URL", "http://intel-embedding:8001")
ASR_URL = os.getenv("ASR_URL", "http://intel-asr:8002")
TRANSLATION_URL = os.getenv("TRANSLATION_URL", "http://intel-translation:8003")
TTS_URL = os.getenv("TTS_URL", "http://intel-tts:8004")

client = httpx.AsyncClient(timeout=60.0)


class HealthResponse(BaseModel):
    status: str
    services: dict


@app.get("/health", response_model=HealthResponse)
async def health():
    services = {}
    
    for name, url in [
        ("embedding", EMBEDDING_URL),
        ("asr", ASR_URL),
        ("translation", TRANSLATION_URL),
        ("tts", TTS_URL),
    ]:
        try:
            resp = await client.get(f"{url}/health", timeout=5.0)
            services[name] = {"status": "healthy", "data": resp.json()}
        except Exception as e:
            services[name] = {"status": "unhealthy", "error": str(e)}
    
    overall = "healthy" if all(s["status"] == "healthy" for s in services.values()) else "degraded"
    
    return HealthResponse(status=overall, services=services)


# --- Embedding endpoints ---
class EmbedRequest(BaseModel):
    texts: List[str]
    normalize: bool = True
    batch_size: Optional[int] = None


@app.post("/embed")
async def embed(req: EmbedRequest):
    resp = await client.post(f"{EMBEDDING_URL}/embed", json=req.model_dump())
    resp.raise_for_status()
    return resp.json()


@app.post("/embed/similarity")
async def similarity(texts_a: List[str], texts_b: List[str], normalize: bool = True):
    resp = await client.post(
        f"{EMBEDDING_URL}/embed/similarity",
        json={"texts_a": texts_a, "texts_b": texts_b, "normalize": normalize},
    )
    resp.raise_for_status()
    return resp.json()


# --- ASR endpoints ---
@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...), language: Optional[str] = Form(None)):
    files = {"file": (file.filename, await file.read(), file.content_type)}
    data = {"language": language} if language else {}
    resp = await client.post(f"{ASR_URL}/transcribe", files=files, data=data)
    resp.raise_for_status()
    return resp.json()


# --- Translation endpoints ---
class TranslateRequest(BaseModel):
    text: str
    source_lang: str = "eng_Latn"
    target_lang: str = "spa_Latn"


@app.post("/translate")
async def translate(req: TranslateRequest):
    resp = await client.post(f"{TRANSLATION_URL}/translate", json=req.model_dump())
    resp.raise_for_status()
    return resp.json()


@app.post("/translate/batch")
async def translate_batch(texts: List[str], source_lang: str = "eng_Latn", target_lang: str = "spa_Latn"):
    resp = await client.post(
        f"{TRANSLATION_URL}/translate/batch",
        json={"texts": texts, "source_lang": source_lang, "target_lang": target_lang},
    )
    resp.raise_for_status()
    return resp.json()


@app.get("/languages")
async def languages():
    resp = await client.get(f"{TRANSLATION_URL}/languages")
    resp.raise_for_status()
    return resp.json()


# --- TTS endpoints ---
class SynthesizeRequest(BaseModel):
    text: str
    voice: Optional[str] = "default"
    format: str = "wav"


@app.post("/synthesize")
async def synthesize(req: SynthesizeRequest):
    resp = await client.post(f"{TTS_URL}/synthesize", json=req.model_dump())
    resp.raise_for_status()
    return resp.json()


@app.get("/voices")
async def voices():
    resp = await client.get(f"{TTS_URL}/voices")
    resp.raise_for_status()
    return resp.json()


# --- OpenAI-compatible endpoints (for compatibility) ---
class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[dict]
    max_tokens: int = 2048
    temperature: float = 0.7
    stream: bool = False


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest):
    """Route to OpenVINO GenAI for LLM chat"""
    ov_url = "http://openvino-genai:8082"
    resp = await client.post(f"{ov_url}/v1/chat/completions", json=req.model_dump())
    resp.raise_for_status()
    return resp.json()


@app.get("/v1/models")
async def list_models():
    """Aggregate models from all services"""
    models = []
    
    # Embedding models
    try:
        resp = await client.get(f"{EMBEDDING_URL}/models")
        data = resp.json()
        for m in data.get("models", []):
            models.append({**m, "owned_by": "intel-embedding"})
    except:
        pass
    
    # OpenVINO GenAI models
    try:
        resp = await client.get("http://openvino-genai:8082/v1/models")
        data = resp.json()
        for m in data.get("data", []):
            models.append({**m, "owned_by": "openvino-genai"})
    except:
        pass
    
    return {"object": "list", "data": models}


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
