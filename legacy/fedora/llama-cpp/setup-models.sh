#!/usr/bin/env bash
# Map the reused Ollama GGUF blobs to friendly <name>.gguf symlinks for llama-swap.
# Relative symlinks so they resolve both on host and inside the container
# (gguf/ and ollama/ are both mounted under /models). Idempotent.
set -euo pipefail
OLLAMA_MODELS="${OLLAMA_MODELS:-/mnt/Shared/models/ollama/models}"
GGUF_DIR="${GGUF_DIR:-/mnt/Shared/models/gguf}"
mkdir -p "$GGUF_DIR"

python3 - "$OLLAMA_MODELS" "$GGUF_DIR" <<'PY'
import json, glob, os, sys
ollama, gguf = sys.argv[1], sys.argv[2]
mdir = os.path.join(ollama, "manifests/registry.ollama.ai/library")
def link(blobdig, name):
    blob = "sha256-" + blobdig.split(":")[1]
    rel  = os.path.relpath(os.path.join(ollama, "blobs", blob), gguf)
    dst  = os.path.join(gguf, name)
    if os.path.islink(dst) or os.path.exists(dst): os.remove(dst)
    os.symlink(rel, dst); print(f"  {name} -> {rel}")
for mf in sorted(glob.glob(mdir + "/*/*")):
    if not os.path.isfile(mf): continue
    model = os.path.basename(os.path.dirname(mf)); tag = os.path.basename(mf)
    d = json.load(open(mf))
    base = model if tag == "latest" else f"{model}-{tag}"
    for L in d.get("layers", []):
        mt = L.get("mediaType", "")
        if mt.endswith("image.model"): link(L["digest"], f"{base}.gguf")
        elif "projector" in mt:        link(L["digest"], f"{base}.mmproj.gguf")
PY
echo "== $GGUF_DIR =="; ls -la "$GGUF_DIR"
