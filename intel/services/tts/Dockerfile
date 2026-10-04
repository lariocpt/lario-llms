FROM openvino/ubuntu24_dev:2026.2.0

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    fastapi uvicorn[standard] \
    transformers accelerate \
    optimum-intel[openvino,nncf] \
    openvino-tokenizers

COPY app.py /app/app.py

ENV TTS_MODEL_DIR=/models/tts/kokoro-82m-int8
ENV TTS_DEVICE=GPU.0
ENV OMP_NUM_THREADS=24
ENV PORT=8004

EXPOSE 8004

CMD ["python", "app.py"]
