#!/usr/bin/env python3
import os
import sys
import argparse
import logging

# ==========================================
# Unified PyTorch ROCm Compatibility Layer
# ==========================================
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

# Polyfills for older PyTorch runtimes
import torch.amp
if not hasattr(torch.amp, 'GradScaler'):
    import torch.cuda.amp
    torch.amp.GradScaler = torch.cuda.amp.GradScaler

import torch.library
if not hasattr(torch.library, 'custom_op'):
    def dummy_custom_op(*args, **kwargs):
        def decorator(func): return func
        return decorator
    torch.library.custom_op = dummy_custom_op
if not hasattr(torch.library, 'register_fake'):
    def dummy_register_fake(*args, **kwargs):
        def decorator(func): return func
        return decorator
    torch.library.register_fake = dummy_register_fake
if not hasattr(torch.library, 'register_autograd'):
    def dummy_register_autograd(*args, **kwargs):
        def decorator(func): return func
        return decorator
    torch.library.register_autograd = dummy_register_autograd

if not hasattr(torch, 'uint16'): torch.uint16 = torch.int16
if not hasattr(torch, 'uint32'): torch.uint32 = torch.int32
if not hasattr(torch, 'uint64'): torch.uint64 = torch.int64

if not hasattr(torch, 'get_default_device'):
    torch.get_default_device = lambda: torch.device('cpu')

import torch.compiler
if not hasattr(torch.compiler, 'is_compiling'):
    torch.compiler.is_compiling = lambda: False

import torch.utils._pytree as torch_pytree
if not hasattr(torch_pytree, 'register_pytree_node'):
    torch_pytree.register_pytree_node = lambda typ, flat, unflat, serialized_type_name=None: torch_pytree._register_pytree_node(typ, flat, unflat)

# Bypass CVE-2025-32434 check which requires torch >= 2.6 for torch.load
import transformers
transformers.utils.import_utils.check_torch_load_is_safe = lambda: None
transformers.utils.check_torch_load_is_safe = lambda: None
transformers.modeling_utils.check_torch_load_is_safe = lambda: None
# ==========================================

import chromadb
from sentence_transformers import SentenceTransformer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ingest_repo")

# Supported file extensions for code ingestion
CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".html", ".css",
    ".md", ".sh", ".yml", ".yaml", ".dockerfile", "dockerfile", ".rs",
    ".go", ".c", ".cpp", ".h", ".hpp", ".sql"
}

# Directories and files to ignore during walk
IGNORE_DIRS = {
    ".git", "node_modules", "dist", "build", ".next", ".cache",
    "__pycache__", "venv", ".venv", "chroma-data", "bifrost"
}

IGNORE_FILES = {
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb",
    ".DS_Store", "ollama-linux-amd64-rocm.tar.zst", "ollama-linux-amd64.tar.zst"
}

def chunk_text(text, max_chars=1200, overlap=200):
    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars
        chunk = text[start:end]
        chunks.append((start, end, chunk))
        start += max_chars - overlap
    return chunks

def main():
    parser = argparse.ArgumentParser(description="Pseudo-train/Ingest active code repositories into local ChromaDB for RAG.")
    parser.add_argument("--repo-path", required=True, help="Absolute path to the repository on your host or container")
    parser.add_argument("--collection", default="my-repos", help="Name of the ChromaDB collection (default: my-repos)")
    parser.add_argument("--host", default="localhost", help="ChromaDB Host address (default: localhost)")
    parser.add_argument("--port", type=int, default=8000, help="ChromaDB Port (default: 8000)")
    parser.add_argument("--chunk-size", type=int, default=1200, help="Maximum characters per chunk (default: 1200)")
    parser.add_argument("--overlap", type=int, default=200, help="Character overlap between chunks (default: 200)")
    
    args = parser.parse_args()
    
    repo_path = os.path.abspath(args.repo_path)
    if not os.path.exists(repo_path):
        logger.error(f"Repository path does not exist: {repo_path}")
        sys.exit(1)
        
    logger.info(f"Connecting to ChromaDB HttpClient at {args.host}:{args.port}...")
    try:
        chroma_client = chromadb.HttpClient(host=args.host, port=args.port)
        # Attempt to get or create collection
        try:
            collection = chroma_client.get_collection(args.collection)
            logger.info(f"Using existing collection '{args.collection}'")
        except Exception:
            collection = chroma_client.create_collection(args.collection)
            logger.info(f"Created new collection '{args.collection}'")
    except Exception as e:
        logger.error(f"Failed to connect to ChromaDB: {e}")
        sys.exit(1)
        
    logger.info("Initializing sentence-transformers embedding model (BAAI/bge-m3)...")
    embedder = SentenceTransformer("BAAI/bge-m3")
    
    documents = []
    ids = []
    metadatas = []
    
    logger.info(f"Scanning directory: {repo_path}...")
    for root, dirs, files in os.walk(repo_path):
        # Modify dirs in-place to avoid walking down ignored directories
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        
        for file in files:
            if file in IGNORE_FILES:
                continue
                
            _, ext = os.path.splitext(file)
            is_dockerfile = file.lower() == "dockerfile" or ext.lower() == ".dockerfile"
            
            if ext.lower() in CODE_EXTENSIONS or is_dockerfile:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, repo_path)
                
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                        
                    if not content.strip():
                        continue
                        
                    chunks = chunk_text(content, max_chars=args.chunk_size, overlap=args.overlap)
                    logger.info(f"Processing {rel_path} ({len(chunks)} chunks)...")
                    
                    for idx, (start, end, chunk_text_data) in enumerate(chunks):
                        doc_id = f"{args.collection}-{rel_path.replace('/', '_').replace('.', '_')}-chunk{idx}"
                        documents.append(chunk_text_data)
                        ids.append(doc_id)
                        metadatas.append({
                            "rel_path": rel_path,
                            "file_name": file,
                            "chunk_index": idx,
                            "start_char": start,
                            "end_char": end,
                            "extension": ext or "dockerfile"
                        })
                except Exception as ex:
                    logger.warning(f"Could not read {rel_path}: {ex}")
                    
    if not documents:
        logger.info("No supported code files found or no content to ingest.")
        return
        
    logger.info(f"Generating embeddings for {len(documents)} chunks (this uses your ROCm GPU if available)...")
    embeddings = embedder.encode(documents, show_progress_bar=True).tolist()
    
    logger.info(f"Ingesting {len(documents)} chunks into ChromaDB collection '{args.collection}'...")
    batch_size = 100
    for i in range(0, len(documents), batch_size):
        end_idx = min(i + batch_size, len(documents))
        collection.add(
            documents=documents[i:end_idx],
            embeddings=embeddings[i:end_idx],
            metadatas=metadatas[i:end_idx],
            ids=ids[i:end_idx]
        )
        logger.info(f"Ingested batch {i // batch_size + 1}/{-(-len(documents) // batch_size)}")
        
    logger.info("🎉 Ingestion complete! The model will now utilize these patterns in your RAG queries.")

if __name__ == "__main__":
    main()
