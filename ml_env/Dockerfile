FROM rocm/pytorch:rocm6.1_ubuntu22.04_py3.10_pytorch_2.1.2

WORKDIR /app

RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip

# Versions pinned to the base image's torch 2.1.2. Unpinned, pip pulls transformers 5.x
# which needs torch>=2.4 (torch.distributed.tensor.DTensor) and rag_api crash-loops on
# `import transformers`. This mid-2024 set is coherent with torch 2.1.2.
RUN pip install --no-cache-dir \
    openai-whisper \
    emm \
    'transformers==4.44.2' \
    'sentence-transformers==3.0.1' \
    'accelerate==0.33.0' \
    'diffusers==0.30.3' \
    chromadb \
    fastapi \
    uvicorn \
    httpx
