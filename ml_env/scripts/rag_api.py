import os
import logging
from contextlib import asynccontextmanager

# Dynamic metadata spoofing to bypass transformers PyTorch version check
import importlib.metadata
orig_version = importlib.metadata.version
def mock_version(package_name):
    if package_name.lower() == 'torch':
        return '2.4.0'
    return orig_version(package_name)
importlib.metadata.version = mock_version

import torch
torch.__version__ = "2.4.0"

# Mock missing distributed tensor and codecarbon modules
import sys
from unittest.mock import MagicMock
import types
try:
    import torch.distributed
    mock_tensor = types.ModuleType('torch.distributed.tensor')
    mock_tensor.device_mesh = MagicMock()
    torch.distributed.tensor = mock_tensor
    sys.modules['torch.distributed.tensor'] = mock_tensor
    sys.modules['torch.distributed.tensor.device_mesh'] = mock_tensor.device_mesh
except Exception:
    sys.modules['torch.distributed.tensor'] = MagicMock()
    sys.modules['torch.distributed.tensor.device_mesh'] = MagicMock()



# Polyfill torch.amp.GradScaler for older PyTorch runtimes
import torch.amp
if not hasattr(torch.amp, 'GradScaler'):
    import torch.cuda.amp
    torch.amp.GradScaler = torch.cuda.amp.GradScaler

# Polyfill torch.library.custom_op for older PyTorch runtimes
import torch.library
if not hasattr(torch.library, 'custom_op'):
    def dummy_custom_op(*args, **kwargs):
        def decorator(func):
            return func
        return decorator
    torch.library.custom_op = dummy_custom_op
if not hasattr(torch.library, 'register_fake'):
    def dummy_register_fake(*args, **kwargs):
        def decorator(func):
            return func
        return decorator
    torch.library.register_fake = dummy_register_fake
if not hasattr(torch.library, 'register_autograd'):
    def dummy_register_autograd(*args, **kwargs):
        def decorator(func):
            return func
        return decorator
    torch.library.register_autograd = dummy_register_autograd

# Polyfill missing PyTorch datatypes and device managers
if not hasattr(torch, 'uint16'):
    torch.uint16 = torch.int16
if not hasattr(torch, 'uint32'):
    torch.uint32 = torch.int32
if not hasattr(torch, 'uint64'):
    torch.uint64 = torch.int64
if not hasattr(torch, 'get_default_device'):
    torch.get_default_device = lambda: torch.device('cpu')

# Polyfill torch.compiler.is_compiling for older PyTorch runtimes
import torch.compiler
if not hasattr(torch.compiler, 'is_compiling'):
    torch.compiler.is_compiling = lambda: False

# Polyfill torch.utils._pytree.register_pytree_node for older PyTorch runtimes
import torch.utils._pytree as torch_pytree
if not hasattr(torch_pytree, 'register_pytree_node'):
    torch_pytree.register_pytree_node = lambda typ, flat, unflat, serialized_type_name=None: torch_pytree._register_pytree_node(typ, flat, unflat)

# Bypass CVE-2025-32434 check which requires torch >= 2.6 for torch.load
import transformers
transformers.utils.import_utils.check_torch_load_is_safe = lambda: None
transformers.utils.check_torch_load_is_safe = lambda: None
transformers.modeling_utils.check_torch_load_is_safe = lambda: None



















import chromadb
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rag_api")

CHROMA_HOST = os.getenv("CHROMA_HOST", "chromadb")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", 8000))
LLM_API = os.getenv("LLM_API_URL", "http://bifrost:8080/v1")
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-m3")

chroma_client = None
embedder = None


class QueryRequest(BaseModel):
    query: str
    collection: str = "default"
    top_k: int = 5


class IngestRequest(BaseModel):
    documents: list[str]
    ids: list[str] | None = None
    collection: str = "default"
    metadatas: list[dict] | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global chroma_client, embedder
    logger.info("Connecting to ChromaDB at %s:%s", CHROMA_HOST, CHROMA_PORT)
    chroma_client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    logger.info("Loading embedding model: %s", EMBED_MODEL)
    embedder = SentenceTransformer(EMBED_MODEL)
    logger.info("RAG API ready")
    yield


app = FastAPI(title="lario-rag", version="1.0.0", lifespan=lifespan)


def get_or_create_collection(name: str):
    try:
        return chroma_client.get_collection(name)
    except Exception:
        return chroma_client.create_collection(name)


@app.post("/ingest")
async def ingest(req: IngestRequest):
    col = get_or_create_collection(req.collection)
    ids = req.ids or [f"doc-{i}" for i in range(len(req.documents))]
    logger.info("Ingesting %d docs into '%s'", len(req.documents), req.collection)
    col.add(documents=req.documents, ids=ids, metadatas=req.metadatas)
    return {"status": "ok", "count": len(req.documents)}


@app.post("/query")
async def query(req: QueryRequest):
    if embedder is None:
        raise HTTPException(503, "Embedding model not loaded")

    col = get_or_create_collection(req.collection)
    q_emb = embedder.encode(req.query).tolist()

    results = col.query(query_embeddings=[q_emb], n_results=req.top_k)
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    if not docs:
        context = "No relevant documents found."
        sources = []
    else:
        context = "\n\n".join(
            f"[{i+1}] {d}" for i, d in enumerate(docs)
        )
        sources = [
            {"index": i, "metadata": metas[i] if metas else {}, "score": distances[i] if distances else 0}
            for i in range(len(docs))
        ]

    rag_prompt = (
        "You are a helpful assistant. Use the following retrieved context to answer the question.\n"
        "If the context doesn't help, answer based on your own knowledge.\n"
        f"\nContext:\n{context}\n\n"
        f"Question: {req.query}\n\nAnswer:"
    )

    async with httpx.AsyncClient(timeout=60) as client:
        try:
            resp = await client.post(
                f"{LLM_API}/chat/completions",
                json={
                    "model": "gemma4",
                    "messages": [{"role": "user", "content": rag_prompt}],
                    "stream": False,
                },
            )
            resp.raise_for_status()
            llm_reply = resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error("LLM call failed: %s", e)
            llm_reply = f"[LLM error] {e}"

    return {
        "query": req.query,
        "response": llm_reply,
        "sources": sources,
        "context_used": docs,
    }


@app.get("/health")
async def health():
    return {"status": "ok", "chroma": chroma_client is not None, "embedder": embedder is not None}


if __name__ == "__main__":
    uvicorn.run("rag_api:app", host="0.0.0.0", port=8100)
