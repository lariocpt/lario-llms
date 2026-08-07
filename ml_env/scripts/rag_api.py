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

# The resident model generates at about 3.3 tokens/sec, measured on the box, and
# every setting below follows from that one number rather than from taste.
#
# Chain-of-thought is off because it is almost all of the cost and none of the
# answer. Same question, same model:
#
#   thinking on   629 tokens  193s   413 chars of answer, 2335 of reasoning
#   thinking off   63 tokens   19s   353 chars of answer
#
# Ten times faster for an answer of the same use. Summarising three retrieved
# passages is not a reasoning task.
LLM_THINKING = os.getenv("LLM_THINKING", "false").lower() in ("1", "true", "yes")

# 512 tokens is roughly 2000 characters — long for a RAG answer — and at 3.3/s it
# is ~155s worst case, which is what sets the timeout below.
#
# If thinking is ever turned back on, this must go ABOVE the server's
# --reasoning-budget (2048): reasoning is spent from the same allowance as the
# answer, so a request capped at 10 returned reasoning_content full and content
# EMPTY. Under that budget the cap does not shorten the answer, it deletes it.
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", 512))

# Was 1800. Half an hour is not a timeout, it is a leak: one wedged call held a
# worker for the whole window while the caller saw an indefinite hang. Sized to
# LLM_MAX_TOKENS at the measured rate, with headroom for prefill.
#
# One thing will blow through it legitimately: an ingest running at the same
# time. /query embeds the question on THIS host's GPU before it ever reaches the
# model host, and ingest_kb.py saturates that same GPU — a query measured at 69s
# idle timed out past 240s while 52k chunks were embedding. That is the system
# being busy, not broken. Raise LLM_TIMEOUT for the duration or, better, do not
# re-ingest a collection while it is being served.
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", 240))

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

    async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
        try:
            resp = await client.post(
                f"{LLM_API}/chat/completions",
                json={
                    # "main" = the fleet's resident model. Never name a specific big
                    # model here — that forces llama-swap to evict the ~87G resident.
                    "model": "main",
                    "messages": [{"role": "user", "content": rag_prompt}],
                    "stream": False,
                    # Uncapped, the server generates against its full context
                    # window — 983040 tokens on the resident model — and a single
                    # RAG answer ran past seven minutes with no way to tell a slow
                    # call from a stuck one.
                    "max_tokens": LLM_MAX_TOKENS,
                    "chat_template_kwargs": {"enable_thinking": LLM_THINKING},
                },
            )
            resp.raise_for_status()
            message = resp.json()["choices"][0]["message"]
            llm_reply = message.get("content") or ""
            if not llm_reply.strip():
                # Empty content with reasoning present means the budget was spent
                # thinking and the answer was truncated away — raise LLM_MAX_TOKENS.
                # Reported rather than returned as a blank success.
                reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
                logger.error("LLM returned no content (reasoning %d chars); "
                             "LLM_MAX_TOKENS=%d may be below the reasoning budget",
                             len(reasoning), LLM_MAX_TOKENS)
                llm_reply = ("[LLM error] empty completion — LLM_MAX_TOKENS "
                             f"({LLM_MAX_TOKENS}) is likely at or below the model's "
                             "reasoning budget")
        except Exception as e:
            # The type matters: httpx timeouts stringify to "", so the old message
            # was a bare "[LLM error]" that said nothing about what went wrong.
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
    return {"status": "ok", "chroma": chroma_client is not None, "embedder": embedder is not None}


if __name__ == "__main__":
    uvicorn.run("rag_api:app", host="0.0.0.0", port=8100)
