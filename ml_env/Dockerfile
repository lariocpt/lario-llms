# ml_env — embedding + ML utility image (rag_api, ml_pipeline).
#
# CUDA build for bigcachy's RTX 5080. The 5080 is Blackwell (sm_120), which needs
# torch >= 2.7 on cu12.8; the host driver is 610.43.03 (CUDA UMD 13.3), so a cu128
# runtime is well within range.
#
# This replaced `rocm/pytorch:rocm6.1_ubuntu22.04_py3.10_pytorch_2.1.2`, which belonged
# to l-dev-ai's Strix Halo. That base forced ~100 lines of version-spoofing polyfills at
# the top of scripts/rag_api.py — including disabling the CVE-2025-32434 torch.load
# safety check — just to run modern transformers on torch 2.1.2. All of it is deleted;
# see the note in rag_api.py.
FROM pytorch/pytorch:2.9.1-cuda12.8-cudnn9-runtime

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip

# Pin the base image's CUDA torch stack into a constraints file BEFORE installing
# anything else. Without this, pip resolves a dependency of sentence-transformers or
# diffusers and happily replaces the cu128 wheels with generic CPU ones — the container
# then starts fine and silently embeds on CPU, which is exactly the failure this whole
# rebuild exists to avoid.
RUN python -c "import torch, torchvision, torchaudio; \
open('/etc/pip-torch-constraints.txt','w').write(''.join([ \
 'torch==%s\n' % torch.__version__, \
 'torchvision==%s\n' % torchvision.__version__, \
 'torchaudio==%s\n' % torchaudio.__version__]))" \
 && cat /etc/pip-torch-constraints.txt

# Unpinned (except via the torch constraints): on a modern torch there is no reason to
# hold transformers/sentence-transformers at the mid-2024 versions the ROCm base needed.
RUN pip install --no-cache-dir -c /etc/pip-torch-constraints.txt \
    openai-whisper \
    emm \
    transformers \
    sentence-transformers \
    accelerate \
    diffusers \
    chromadb \
    fastapi \
    uvicorn \
    httpx \
    gspread \
    google-auth

# Fail the build rather than ship an image that would quietly fall back to CPU.
RUN python -c "import torch, transformers, sentence_transformers as st; \
print('torch', torch.__version__, '| transformers', transformers.__version__, '| st', st.__version__); \
assert torch.version.cuda, 'torch has no CUDA support - a CPU wheel leaked in'; \
print('cuda', torch.version.cuda, '| arch_list', torch.cuda.get_arch_list())"
