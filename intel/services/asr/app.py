"""Multilingual ASR using OpenVINO GenAI's complete Whisper pipeline."""
import io
import os
import subprocess
import threading
import time
from contextlib import asynccontextmanager

import numpy as np
import openvino as ov
import openvino_genai as genai
from fastapi import FastAPI, File, Form, HTTPException, UploadFile

MODEL_DIR = os.environ.get('ASR_MODEL_DIR', '/mnt/xfs/AI_Models/openvino/asr/whisper-large-v3-turbo-fp16')
DEVICE = os.environ.get('ASR_DEVICE', 'NPU')
pipe = None
lock = threading.Lock()

@asynccontextmanager
async def lifespan(app):
    global pipe
    pipe = genai.WhisperPipeline(MODEL_DIR, DEVICE)
    yield

app = FastAPI(title='Intel multilingual Whisper ASR', lifespan=lifespan)

@app.post('/transcribe')
def transcribe(file: UploadFile = File(...), language: str | None = Form(None), task: str = Form('transcribe')):
    if task != 'transcribe':
        raise HTTPException(400, 'Whisper turbo supports transcription; use /translate on port 8003 for text translation')
    if pipe is None:
        raise HTTPException(503, 'Model is not ready')
    content = file.file.read(50_000_001)
    if len(content) > 50_000_000:
        raise HTTPException(413, 'Audio upload exceeds 50 MB')
    start = time.perf_counter()
    decoded = subprocess.run(['ffmpeg','-v','error','-i','pipe:0','-f','f32le','-ac','1','-ar','16000','pipe:1'],
                             input=content, capture_output=True, timeout=120)
    if decoded.returncode:
        raise HTTPException(400, 'Invalid or unsupported audio')
    audio = np.frombuffer(decoded.stdout, dtype=np.float32)
    if not audio.size or audio.size > 16000*1800:
        raise HTTPException(400, 'Audio must be between zero and 1800 seconds')
    options = {'task': task, 'max_new_tokens': 448}
    if language:
        options['language'] = language if language.startswith('<|') else f'<|{language}|>'
    with lock:
        result = pipe.generate(audio, **options)
    return {'text': ''.join(result.texts).strip(), 'language': language, 'task': task,
            'duration_sec': len(audio)/16000, 'processing_time_ms': (time.perf_counter()-start)*1000,
            'model': os.path.basename(MODEL_DIR), 'device': DEVICE}

@app.get('/health')
def health():
    return {'status': 'healthy' if pipe is not None else 'unavailable', 'model_loaded': pipe is not None,
            'model': os.path.basename(MODEL_DIR), 'device': DEVICE, 'available_devices': ov.Core().available_devices}

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host=os.environ.get('BIND_HOST', '127.0.0.1'), port=8002)
