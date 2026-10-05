# Intel Embedding Service - OpenVINO on CPU/GPU.0
FROM ubuntu:24.04

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    fastapi uvicorn[standard] \
    transformers accelerate \
    optimum-intel[openvino,nncf] \
    openvino-tokenizers

# Copy service code
COPY app.py /app/app.py

# Model directory will be mounted from host
ENV EMBEDDING_MODEL_DIR=/models/embeddings/e5-small-v2-int8
ENV PORT=8001
ENV OMP_NUM_THREADS=24

EXPOSE 8001

CMD ["python", "app.py"]
