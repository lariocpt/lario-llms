import os
import logging
from contextlib import asynccontextmanager

import chromadb
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rag_api")

CHROMA_HOST = os.getenv("CHROMA_HOST", "chromadb")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", 8000))
LLM_API = os.getenv("LLM_API_URL", "http://bifrost:8080/v1")
# Use Intel embedding service (E5-base-v2 for English, BGE-M3 for multi-lingual)
INTEL_EMBED_URL = os.getenv("INTEL_EMBED_URL", "http://intel-embedding:8001")
DEFAULT_EMBED_MODEL = os.getenv("DEFAULT_EMBED_MODEL", "bge-m3-int8")

LLM_THINKING = os.getenv("LLM_THINKING", "false").lower() in ("1", "true", "yes")
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", 512))
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", 240))

chroma_client = None
embed_client = None


class QueryRequest(BaseModel):
    model: str | None = None  # e5-base-v2-int8, bge-m3-int8, e5-small-v2-int8
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
    model: str | None = None  # e5-base-v2-int8, bge-m3-int8, e5-small-v2-int8


class RetrieveRequest(BaseModel):
    query: str
    collection: str = "default"
    top_k: int = 5


@asynccontextmanager
async def lifespan(app: FastAPI):
    global chroma_client, embed_client
    logger.info("Connecting to ChromaDB at %s:%s", CHROMA_HOST, CHROMA_PORT)
    chroma_client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    
    # Create async HTTP client for Intel embedding service
    embed_client = httpx.AsyncClient(base_url=INTEL_EMBED_URL, timeout=30.0)
    
    # Verify Intel embedding service is healthy
    try:
        resp = await embed_client.get("/health")
        resp.raise_for_status()
        health = resp.json()
        logger.info("Intel embedding service ready: %s on %s", health.get("current_model"), health.get("device"))
    except Exception as e:
        logger.warning("Intel embedding service not ready: %s", e)
    
    logger.info("RAG API ready (using Intel embeddings at %s)", INTEL_EMBED_URL)
    yield
    
    await embed_client.aclose()


app = FastAPI(title="lario-rag", version="2.0.0", lifespan=lifespan)


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


async def _embed_texts(texts: list[str], model: str | None = None) -> list[list[float]]:
    """Embed texts using Intel embedding service."""
    if embed_client is None:
        raise HTTPException(503, "Embedding client not initialized")
    
    model = model or DEFAULT_EMBED_MODEL
    resp = await embed_client.post(
        "/embed",
        json={"texts": texts, "normalize": True, "model": model}
    )
    resp.raise_for_status()
    data = resp.json()
    return data["embeddings"]


@app.post("/embed")
async def embed(req: EmbedRequest):
    """Embed texts with Intel embedding service. Lets thin clients upsert consistently."""
    vectors = await _embed_texts(req.texts, req.model)
    return {"model": req.model or DEFAULT_EMBED_MODEL, "embeddings": vectors}


@app.post("/retrieve")
async def retrieve(req: RetrieveRequest):
    """Pure vector search — docs/metadatas/distances, NO LLM call."""
    if embed_client is None:
        raise HTTPException(503, "Embedding client not initialized")
    col = get_or_create_collection(req.collection)
    q_emb = await _embed_texts([req.query], req.model or DEFAULT_EMBED_MODEL)
    results = col.query(query_embeddings=q_emb, n_results=req.top_k)
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
    if embed_client is None:
        raise HTTPException(503, "Embedding client not initialized")

    col = get_or_create_collection(req.collection)
    q_emb = await _embed_texts([req.query], req.model or DEFAULT_EMBED_MODEL)

    results = col.query(query_embeddings=q_emb, n_results=req.top_k)
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

    async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
        try:
            resp = await client.post(
                f"{LLM_API}/chat/completions",
                json={
                    "model": "main",
                    "messages": [{"role": "user", "content": rag_prompt}],
                    "stream": False,
                    "max_tokens": LLM_MAX_TOKENS,
                    "chat_template_kwargs": {"enable_thinking": LLM_THINKING},
                },
            )
            resp.raise_for_status()
            message = resp.json()["choices"][0]["message"]
            llm_reply = message.get("content") or ""
            if not llm_reply.strip():
                reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
                logger.error("LLM returned no content (reasoning %d chars); "
                             "LLM_MAX_TOKENS=%d may be below the reasoning budget",
                             len(reasoning), LLM_MAX_TOKENS)
                llm_reply = ("[LLM error] empty completion — LLM_MAX_TOKENS "
                             f"({LLM_MAX_TOKENS}) is likely at or below the model's "
                             "reasoning budget")
        except Exception as e:
            logger.error("LLM call failed: %s: %s", type(e).__name__, e)
            llm_reply = f"[LLM error] {type(e).__name__}: {e}"

    return {
        "query": req.query,
        "response": llm_reply,
        "sources": sources,
        "context_used": docs,
    }


@app.get("/health")
async def health():
    return {"status": "ok", "chroma": chroma_client is not None, "embedder": embed_client is not None}


if __name__ == "__main__":
    uvicorn.run("rag_api:app", host="0.0.0.0", port=8100)
