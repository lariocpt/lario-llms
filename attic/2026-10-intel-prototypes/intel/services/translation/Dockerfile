FROM openvino/ubuntu24_dev:2026.2.0

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    fastapi uvicorn[standard] \
    transformers accelerate \
    optimum-intel[openvino,nncf] \
    openvino-tokenizers

COPY app.py /app/app.py

ENV TRANSLATION_MODEL_DIR=/models/translation/nllb-200-distilled-600m-int8
ENV TRANSLATION_DEVICE=NPU
ENV OMP_NUM_THREADS=24
ENV PORT=8003

EXPOSE 8003

CMD ["python", "app.py"]
