FROM openvino/ubuntu24_dev:2026.2.0

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    fastapi uvicorn[standard] python-multipart \
    transformers accelerate librosa \
    optimum-intel[openvino,nncf] \
    openvino-tokenizers

COPY app.py /app/app.py

ENV ASR_MODEL_DIR=/models/asr/distil-whisper-large-v3-int8
ENV ASR_ENCODER_DEVICE=GPU.0
ENV ASR_DECODER_DEVICE=CPU
ENV OMP_NUM_THREADS=24
ENV PORT=8002

EXPOSE 8002

CMD ["python", "app.py"]
