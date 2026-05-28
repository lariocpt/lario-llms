FROM rocm/pytorch:rocm6.1_ubuntu22.04_py3.10_pytorch_2.1.2

WORKDIR /app

RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip

RUN pip install --no-cache-dir \
    openai-whisper \
    emm \
    sentence-transformers \
    diffusers \
    transformers \
    accelerate \
    chromadb \
    fastapi \
    uvicorn \
    httpx
