#!/usr/bin/env python3
"""
Intel Embedding Service - Text embeddings on CPU/GPU.0 via OpenVINO
Models: E5-base-v2 (default, 768-dim), BGE-M3 (multi-lingual, 1024-dim)
Note: NPU not supported for transformer attention ops (ZE_RESULT_ERROR_UNSUPPORTED_FEATURE)
"""

import os
import time
from pathlib import Path
from typing import List, Optional, Dict

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

os.environ["OMP_NUM_THREADS"] = "24"

from openvino import Core
from transformers import AutoTokenizer


# Configuration - Model registry
MODEL_REGISTRY: Dict[str, Dict] = {
    "e5-base-v2-int8": {
        "path": "/models/embeddings/e5-base-v2-int8",
        "dim": 768,
        "description": "English embedding, 110M params, 768-dim, 104 vec/s CPU",
    },
    "bge-m3-int8": {
        "path": "/models/embeddings/bge-m3-int8",
        "dim": 1024,
        "description": "Multi-lingual embedding, 567M params, 1024-dim, 30 vec/s CPU",
    },
    "e5-small-v2-int8": {
        "path": "/models/embeddings/e5-small-v2-int8",
        "dim": 384,
        "description": "English embedding, 33M params, 384-dim, 344 vec/s CPU (fast)",
    },
}

DEFAULT_MODEL = os.getenv("DEFAULT_EMBEDDING_MODEL", "e5-base-v2-int8")
DEVICE_PRIORITY = ["CPU", "GPU.0"]
BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "32"))
MAX_SEQ_LEN = int(os.getenv("EMBEDDING_MAX_SEQ_LEN", "512"))

app = FastAPI(
    title="Intel Embedding Service",
    version="1.0.0",
    description="Text embeddings on Intel CPU/iGPU via OpenVINO (NPU not supported for attention)",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request/Response Models
class EmbedRequest(BaseModel):
    texts: List[str] = Field(..., min_length=1, max_length=1000)
    normalize: bool = Field(True, description="L2-normalize embeddings")
    batch_size: Optional[int] = Field(None, ge=1, le=256)
    model: Optional[str] = Field(None, description="Model to use (e5-base-v2-int8, bge-m3-int8, e5-small-v2-int8)")


class EmbedResponse(BaseModel):
    embeddings: List[List[float]]
    model: str
    device: str
    dimensions: int
    batch_size: int
    processing_time_ms: float


class SimilarityRequest(BaseModel):
    texts_a: List[str] = Field(..., min_length=1)
    texts_b: List[str] = Field(..., min_length=1)
    normalize: bool = Field(True)
    model: Optional[str] = Field(None)


class SimilarityResponse(BaseModel):
    similarities: List[List[float]]
    model: str
    device: str


class HealthResponse(BaseModel):
    status: str
    default_model: str
    available_models: List[Dict[str, str]]
    current_model: str
    device: str
    model_loaded: bool
    available_devices: List[str]
    note: Optional[str] = None


class ModelInfoResponse(BaseModel):
    models: List[Dict[str, str]]
    default: str


# Global state
core = Core()
compiled_models: Dict[str, object] = {}
tokenizers: Dict[str, object] = {}
active_model_name = DEFAULT_MODEL
active_device = None
load_error: Optional[str] = None


def select_device() -> str:
    for dev in DEVICE_PRIORITY:
        if dev in core.available_devices:
            return dev
    return "CPU"


def load_model(model_key: str) -> bool:
    """Load and compile a specific model."""
    global compiled_models, tokenizers, load_error
    
    if model_key not in MODEL_REGISTRY:
        load_error = f"Unknown model: {model_key}"
        return False
    
    if model_key in compiled_models:
        return True
    
    config = MODEL_REGISTRY[model_key]
    model_path = Path(config["path"]) / "openvino_model.xml"
    
    if not model_path.exists():
        load_error = f"Model not found at {model_path}"
        print(f"ERROR: {load_error}")
        return False
    
    try:
        device = select_device()
        print(f"Loading {model_key} on {device}...")
        
        tokenizer = AutoTokenizer.from_pretrained(config["path"])
        
        config_dict = {"PERFORMANCE_HINT": "THROUGHPUT"}
        if device == "GPU.0":
            config_dict["GPU_THROUGHPUT_STREAMS"] = "4"
        
        compiled = core.compile_model(str(model_path), device, config_dict)
        
        # Warmup
        test_inputs = tokenizer(
            ["warmup"], padding=True, truncation=True, max_length=MAX_SEQ_LEN, return_tensors="np"
        )
        _ = compiled(dict(test_inputs))
        
        compiled_models[model_key] = compiled
        tokenizers[model_key] = tokenizer
        print(f"Model {model_key} loaded successfully on {device}")
        load_error = None
        return True
        
    except Exception as e:
        load_error = str(e)
        print(f"Model {model_key} load failed: {e}")
        return False


@app.on_event("startup")
async def startup():
    # Load default model
    if not load_model(DEFAULT_MODEL):
        print(f"WARNING: Failed to load default model {DEFAULT_MODEL}")
    # Pre-load other models in background
    import threading
    def preload():
        for m in MODEL_REGISTRY:
            if m != DEFAULT_MODEL:
                load_model(m)
    threading.Thread(target=preload, daemon=True).start()


def mean_pooling(token_embeddings: np.ndarray, attention_mask: np.ndarray) -> np.ndarray:
    mask = attention_mask[:, :, np.newaxis].astype(np.float32)
    summed = np.sum(token_embeddings * mask, axis=1)
    counts = np.clip(np.sum(mask, axis=1), a_min=1e-9, a_max=None)
    return summed / counts


def normalize_embeddings(embeddings: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    return embeddings / np.clip(norms, a_min=1e-12, a_max=None)


def get_model(model_key: Optional[str]) -> str:
    """Resolve model key, default to active model."""
    if model_key is None:
        return active_model_name
    if model_key not in MODEL_REGISTRY:
        raise HTTPException(status_code=400, detail=f"Unknown model: {model_key}. Available: {list(MODEL_REGISTRY.keys())}")
    if not load_model(model_key):
        raise HTTPException(status_code=503, detail=f"Failed to load model: {load_error}")
    return model_key


@app.post("/embed", response_model=EmbedResponse)
async def embed(req: EmbedRequest):
    model_key = get_model(req.model)
    config = MODEL_REGISTRY[model_key]
    compiled = compiled_models[model_key]
    tokenizer = tokenizers[model_key]
    
    start_time = time.perf_counter()
    batch_size = req.batch_size or BATCH_SIZE
    all_embeddings = []
    
    for i in range(0, len(req.texts), batch_size):
        batch_texts = req.texts[i:i + batch_size]
        
        inputs = tokenizer(
            batch_texts,
            padding=True,
            truncation=True,
            max_length=MAX_SEQ_LEN,
            return_tensors="np",
        )
        
        result = compiled(dict(inputs))
        token_embeddings = result[compiled.output(0)]
        
        embeddings = mean_pooling(token_embeddings, inputs["attention_mask"])
        
        if req.normalize:
            embeddings = normalize_embeddings(embeddings)
        
        all_embeddings.append(embeddings)
    
    final_embeddings = np.vstack(all_embeddings) if len(all_embeddings) > 1 else all_embeddings[0]
    processing_time = (time.perf_counter() - start_time) * 1000
    
    return EmbedResponse(
        embeddings=final_embeddings.tolist(),
        model=model_key,
        device=active_device or select_device(),
        dimensions=config["dim"],
        batch_size=batch_size,
        processing_time_ms=processing_time,
    )


@app.post("/embed/similarity", response_model=SimilarityResponse)
async def similarity(req: SimilarityRequest):
    model_key = get_model(req.model)
    compiled = compiled_models[model_key]
    tokenizer = tokenizers[model_key]
    
    all_texts = req.texts_a + req.texts_b
    embed_resp = await embed(EmbedRequest(texts=all_texts, normalize=req.normalize, batch_size=BATCH_SIZE, model=model_key))
    embeddings = np.array(embed_resp.embeddings)
    
    emb_a = embeddings[:len(req.texts_a)]
    emb_b = embeddings[len(req.texts_a):]
    
    similarities = emb_a @ emb_b.T
    
    return SimilarityResponse(
        similarities=similarities.tolist(),
        model=model_key,
        device=active_device or select_device(),
    )


@app.post("/model/switch")
async def switch_model(model: str):
    """Switch the default model."""
    global active_model_name
    if model not in MODEL_REGISTRY:
        raise HTTPException(status_code=400, detail=f"Unknown model: {model}")
    if not load_model(model):
        raise HTTPException(status_code=503, detail=f"Failed to load model: {load_error}")
    active_model_name = model
    return {"status": "ok", "active_model": active_model_name}


@app.get("/health", response_model=HealthResponse)
async def health():
    available = []
    for key, info in MODEL_REGISTRY.items():
        available.append({"id": key, "dimensions": str(info["dim"]), "description": info["description"]})
    
    return HealthResponse(
        status="healthy" if load_error is None else "degraded",
        default_model=DEFAULT_MODEL,
        available_models=available,
        current_model=active_model_name,
        device=active_device or select_device(),
        model_loaded=active_model_name in compiled_models,
        available_devices=core.available_devices,
        note="NPU not supported for transformer attention (ZE_RESULT_ERROR_UNSUPPORTED_FEATURE). Using CPU/GPU.0."
    )


@app.get("/models", response_model=ModelInfoResponse)
async def models():
    return ModelInfoResponse(
        models=[
            {"id": k, "name": k, "dimensions": str(v["dim"]), "description": v["description"]}
            for k, v in MODEL_REGISTRY.items()
        ],
        default=DEFAULT_MODEL,
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8001"))
    uvicorn.run(app, host="0.0.0.0", port=port)
