import os
import logging
from contextlib import asynccontextmanager

# NOTE (2026-07, fleet move to bigcachy): ~100 lines of compatibility scaffolding used to
# sit here. It spoofed `torch.__version__` to "2.4.0", monkeypatched
# importlib.metadata.version to lie about torch, mocked torch.distributed.tensor, and
# polyfilled ~10 torch APIs — all to run modern transformers on the ROCm base image's
# torch 2.1.2. It also disabled transformers' CVE-2025-32434 torch.load safety check in
# three places, which was only "safe" because nothing else could work.
#
# The image is now built on pytorch/pytorch:2.9.1-cuda12.8-cudnn9-runtime (see
# ../Dockerfile) for the RTX 5080 (Blackwell, sm_120). Every one of those APIs is native
# in torch 2.9, and the CVE check passes legitimately on torch >= 2.6 — so the whole
# block is deleted rather than carried forward. torch is not imported here at all now:
# sentence-transformers pulls it in itself.

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


class EmbedRequest(BaseModel):
    texts: list[str]


class RetrieveRequest(BaseModel):
    query: str
    collection: str = "default"
    top_k: int = 5


@asynccontextmanager
async def lifespan(app: FastAPI):
    global chroma_client, embedder
    logger.info("Connecting to ChromaDB at %s:%s", CHROMA_HOST, CHROMA_PORT)
    chroma_client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    logger.info("Loading embedding model: %s", EMBED_MODEL)
    # fp16, not the SentenceTransformer default of fp32 (2026-08-01). This process is not
    # alone on the card: the `vision` service (Qwen3-VL-8B) swaps in beside it on demand,
    # and bge-m3 in fp32 held 4.0-4.3GB of the 5080's 16GB — enough that vision's KV cache
    # could not be allocated and llama-server died on startup, breaking every image call
    # fleet-wide. bge-m3 is a 568M encoder; fp16 halves the weights with no meaningful
    # accuracy cost (verified: cosine similarity vs the fp32 vectors >= 0.9999, and
    # retrieval order over kb-muscledynamix was unchanged).
    #
    # Existing collections were embedded in fp32. That stays fine BECAUSE the drift is
    # this small and every vector is normalize_embeddings=True — do not extend this to a
    # different model or a lower dtype without re-embedding the collections.
    embedder = SentenceTransformer(EMBED_MODEL, model_kwargs={"torch_dtype": "float16"})
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


@app.post("/embed")
async def embed(req: EmbedRequest):
    """Embed texts with the server's model (bge-m3). Lets thin clients (agent
    containers with no ML stack) upsert into collections consistently."""
    if embedder is None:
        raise HTTPException(503, "Embedding model not loaded")
    vectors = embedder.encode(req.texts, normalize_embeddings=True).tolist()
    return {"model": EMBED_MODEL, "embeddings": vectors}


@app.post("/retrieve")
async def retrieve(req: RetrieveRequest):
    """Pure vector search — docs/metadatas/distances, NO LLM call. Unlike /query
    this never touches the model backend (so it can never trigger a model swap)."""
    if embedder is None:
        raise HTTPException(503, "Embedding model not loaded")
    col = get_or_create_collection(req.collection)
    q_emb = embedder.encode(req.query, normalize_embeddings=True).tolist()
    results = col.query(query_embeddings=[q_emb], n_results=req.top_k)
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]
    return {
        "query": req.query,
        "results": [
            {"document": docs[i],
             "metadata": metas[i] if metas else {},
             "distance": distances[i] if distances else None}
            for i in range(len(docs))
        ],
    }


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

    async with httpx.AsyncClient(timeout=1800) as client:
        try:
            resp = await client.post(
                f"{LLM_API}/chat/completions",
                json={
                    # "main" = the fleet's resident model. Never name a specific big
                    # model here — that forces llama-swap to evict the ~87G resident.
                    "model": "main",
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
