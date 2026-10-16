import os
import json
import logging
import math
import re
from contextlib import asynccontextmanager

import chromadb
from chromadb.errors import NotFoundError
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from rag_access import authorize, trusted
from pydantic import BaseModel
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rag_api")

CHROMA_HOST = os.getenv("CHROMA_HOST", "chromadb")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", 8000))
LLM_API = os.getenv("LLM_API_URL", "http://192.168.2.1:11434/v1")
# Fixed BGE-M3 space: CLS pooling, normalized, 1024 dimensions.
INTEL_EMBED_URL = os.getenv("INTEL_EMBED_URL", "http://host.docker.internal:8001")
DEFAULT_EMBED_MODEL = os.getenv("DEFAULT_EMBED_MODEL", "BAAI/bge-m3")

LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "geekom")
LLM_THINKING = os.getenv("LLM_THINKING", "false").lower() in ("1", "true", "yes")
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", 512))
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", 240))

chroma_client = None
embed_client = None


class QueryRequest(BaseModel):
    model: str | None = None  # only BAAI/bge-m3
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
    model: str | None = None  # only BAAI/bge-m3


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
    embed_client = httpx.AsyncClient(base_url=INTEL_EMBED_URL, timeout=300.0)
    
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

@app.middleware("http")
async def kb_access(request: Request, call_next):
    if request.method == "POST":
        parts = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > 4_000_000:
                return JSONResponse({"error": "request too large"}, status_code=413)
            parts.append(chunk)
        raw = b"".join(parts)
        request._body = raw
        try: body = json.loads(raw)
        except (ValueError, UnicodeError):
            return JSONResponse({"error": "invalid JSON"}, status_code=400)
    else:
        body = {}
    if not authorize(request.url.path, body, request.headers.get("authorization")):
        return JSONResponse({"error": "KB route requires trusted maintenance authorization"}, status_code=403)
    return await call_next(request)

async def mapped_retrieve(req):
    mapper = os.getenv("KB_MAPPING_URL", "")
    if not mapper:
        raise HTTPException(503, "shared knowledge mapping is unconfigured")
    try:
        async with httpx.AsyncClient(timeout=300, trust_env=False) as client:
            response = await client.post(mapper.rstrip('/') + "/retrieve", json=req.model_dump())
    except httpx.HTTPError:
        raise HTTPException(503, "shared knowledge mapping unavailable")
    try:
        body = response.json()
    except ValueError:
        raise HTTPException(503, "invalid shared knowledge mapping response") from None
    if response.status_code == 200:
        if (not isinstance(body, dict) or body.get('scope') != req.collection
                or not isinstance(body.get('generation'), str) or not body['generation']
                or not isinstance(body.get('results'), list) or len(body['results']) > req.top_k):
            raise HTTPException(503, "invalid shared knowledge mapping response")
        for hit in body['results']:
            if (not isinstance(hit, dict) or not isinstance(hit.get('document'), str)
                    or not isinstance(hit.get('metadata'), dict)
                    or (hit.get('distance') is not None and
                        (type(hit['distance']) not in (int, float) or not math.isfinite(hit['distance'])))):
                raise HTTPException(503, "invalid shared knowledge mapping response")
        return body
    # Existing collections remain read-only during first publication; an active
    # generation failure must never silently fall back to legacy evidence.
    if (response.status_code == 404 and isinstance(body, dict)
            and body.get('error') == 'scope has no active generation'
            and body.get('legacy_allowed') is True):
        return None
    raise HTTPException(503, "shared knowledge generation unavailable")



def get_or_create_collection(name: str):
    try:
        return chroma_client.get_collection(name)
    except NotFoundError:
        return chroma_client.create_collection(name)
    except Exception:
        raise HTTPException(503, "shared knowledge storage unavailable") from None


@app.post("/ingest")
async def ingest(req: IngestRequest):
    col = get_or_create_collection(req.collection)
    ids = req.ids or [f"doc-{i}" for i in range(len(req.documents))]
    logger.info("Ingesting %d docs into '%s'", len(req.documents), req.collection)
    vectors = await _embed_texts(req.documents)
    col.add(documents=req.documents, ids=ids, metadatas=req.metadatas, embeddings=vectors)
    return {"status": "ok", "count": len(req.documents)}


async def _embed_texts(texts: list[str], model: str | None = None) -> list[list[float]]:
    """Embed texts using Intel embedding service."""
    if embed_client is None:
        raise HTTPException(503, "Embedding client not initialized")
    
    model = model or DEFAULT_EMBED_MODEL
    if model != DEFAULT_EMBED_MODEL:
        raise HTTPException(400, "RAG uses a fixed embedding space: " + DEFAULT_EMBED_MODEL)
    resp = await embed_client.post(
        "/embed",
        json={"texts": texts, "normalize": True, "model": model}
    )
    resp.raise_for_status()
    data = resp.json()
    vectors = data["embeddings"]
    if len(vectors) != len(texts) or any(len(v) != 1024 for v in vectors):
        raise HTTPException(502, "Embedding backend violated the 1024-dimensional BGE-M3 contract")
    return vectors


@app.post("/embed")
async def embed(req: EmbedRequest):
    """Embed texts with Intel embedding service. Lets thin clients upsert consistently."""
    vectors = await _embed_texts(req.texts, req.model)
    return {"model": req.model or DEFAULT_EMBED_MODEL, "embeddings": vectors}


@app.post("/retrieve")
async def retrieve(req: RetrieveRequest, request: Request):
    """Pure vector search — docs/metadatas/distances, NO LLM call."""
    if not trusted(request.headers.get("authorization")):
        mapped = await mapped_retrieve(req)
        if mapped is not None:
            return mapped
    if embed_client is None:
        raise HTTPException(503, "Embedding client not initialized")
    try:
        col = chroma_client.get_collection(req.collection)
    except NotFoundError:
        raise HTTPException(404, "shared knowledge has not been published")
    except Exception:
        raise HTTPException(503, "shared knowledge storage unavailable") from None
    q_emb = await _embed_texts([req.query])
    results = col.query(query_embeddings=q_emb, n_results=req.top_k)
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]
    return {
        "query": req.query,
        "generation": "legacy",
        "provenance": "legacy collection retained pending verified publication",
        "results": [
            {"document": docs[i],
             "metadata": metas[i] if metas else {},
             "distance": distances[i] if distances else None}
            for i in range(len(docs))
        ],
    }


@app.post("/query")
async def query(req: QueryRequest, request: Request):
    if req.model is not None and req.model != DEFAULT_EMBED_MODEL:
        raise HTTPException(400, "RAG uses a fixed embedding space: " + DEFAULT_EMBED_MODEL)

    retrieval = await retrieve(RetrieveRequest(query=req.query, collection=req.collection, top_k=req.top_k), request)
    hits = retrieval["results"]
    docs = [r["document"] for r in hits]
    metas = [r.get("metadata", {}) for r in hits]
    distances = [r.get("distance") for r in hits]

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
                headers={"Authorization": "Bearer " + LLM_API_KEY} if LLM_API_KEY else {},
                json={
                    "model": LLM_MODEL,
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
        **{key: retrieval[key] for key in ('scope', 'generation', 'revision', 'provenance') if key in retrieval},
    }


@app.get("/health")
async def health():
    return {"status": "ok", "chroma": chroma_client is not None, "embedder": embed_client is not None}


@app.api_route("/chroma/{route:path}", methods=["GET", "POST"])
async def trusted_chroma(route: str, request: Request):
    if not trusted(request.headers.get("authorization")):
        raise HTTPException(403, "trusted storage authorization required")
    base = "api/v2/tenants/default_tenant/databases/default_database/collections"
    suffix = 'count' if request.method == 'GET' else 'add'
    if not re.fullmatch(re.escape(base) + r"(?:/[a-zA-Z0-9-]+/" + suffix + r")?", route):
        raise HTTPException(403, "storage operation is outside publication contract")
    try:
        async with httpx.AsyncClient(timeout=300, trust_env=False) as client:
            response = await client.request(request.method, "http://chromadb:8000/" + route,
                                            content=await request.body(),
                                            headers={"Content-Type": "application/json"})
    except httpx.HTTPError:
        raise HTTPException(503, "trusted storage unavailable")
    return Response(content=response.content, status_code=response.status_code, media_type="application/json")


if __name__ == "__main__":
    uvicorn.run("rag_api:app", host="0.0.0.0", port=8100)
