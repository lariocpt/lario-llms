"""Fixed BGE-M3 dense embedding space for the fleet's existing Chroma collections."""
import os
import threading
import time
from contextlib import asynccontextmanager

import numpy as np
import openvino as ov
import openvino_genai as genai
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

MODEL = 'BAAI/bge-m3'
MODEL_DIR = os.environ.get('EMBEDDING_MODEL_DIR', '/mnt/xfs/AI_Models/openvino/embeddings/bge-m3-fp16')
DEVICE = os.environ.get('EMBEDDING_DEVICE', 'CPU')
pipe = None
lock = threading.Lock()

@asynccontextmanager
async def lifespan(app):
    global pipe
    cfg = genai.TextEmbeddingPipeline.Config()
    cfg.pooling_type = genai.TextEmbeddingPipeline.PoolingType.CLS
    cfg.normalize = True
    cfg.max_length = 8192
    pipe = genai.TextEmbeddingPipeline(MODEL_DIR, DEVICE, cfg)
    vector = np.asarray(pipe.embed_documents(['warmup']))
    if vector.shape != (1, 1024) or not np.isfinite(vector).all():
        raise RuntimeError('BGE-M3 startup contract failed')
    yield

app = FastAPI(title='Intel BGE-M3 embeddings', lifespan=lifespan)

class EmbedRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=256)
    model: str | None = None
    normalize: bool = True
    batch_size: int | None = Field(default=None, ge=1, le=32)

@app.post('/embed')
def embed(req: EmbedRequest):
    if req.model not in (None, MODEL):
        raise HTTPException(400, f'Fixed RAG embedding space: {MODEL}; reindex separately to change models')
    if not req.normalize:
        raise HTTPException(400, 'RAG requires normalized embeddings')
    if pipe is None:
        raise HTTPException(503, 'Model is not ready')
    start = time.perf_counter()
    vectors = []
    # Serialize access: GenAI pipeline inference requests are not shared across threads.
    with lock:
        for i in range(0, len(req.texts), req.batch_size or 4):
            vectors.extend(np.asarray(pipe.embed_documents(req.texts[i:i+(req.batch_size or 4)])).tolist())
    return {'embeddings': vectors, 'model': MODEL, 'device': DEVICE, 'dimensions': 1024,
            'processing_time_ms': (time.perf_counter()-start)*1000}

@app.get('/health')
def health():
    return {'status': 'healthy' if pipe is not None else 'unavailable', 'model_loaded': pipe is not None,
            'current_model': MODEL, 'device': DEVICE, 'available_devices': ov.Core().available_devices,
            'pooling': 'CLS', 'normalize': True, 'max_length': 8192, 'dimensions': 1024}

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host=os.environ.get('BIND_HOST', '127.0.0.1'), port=8001)
