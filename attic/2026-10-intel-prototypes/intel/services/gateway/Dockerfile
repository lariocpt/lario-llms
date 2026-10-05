FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    fastapi uvicorn[standard] httpx python-multipart

COPY app.py /app/app.py

ENV EMBEDDING_URL=http://intel-embedding:8001
ENV ASR_URL=http://intel-asr:8002
ENV TRANSLATION_URL=http://intel-translation:8003
ENV TTS_URL=http://intel-tts:8004
ENV OMP_NUM_THREADS=24
ENV PORT=8000

EXPOSE 8000

CMD ["python", "app.py"]
