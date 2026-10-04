#!/usr/bin/env python3
"""
Intel ASR Service - Speech-to-Text on iGPU (encoder) + CPU (decoder)
Distil-Whisper-Large-v3 INT8 via OpenVINO
"""

import os
import time
import uuid
import tempfile
from pathlib import Path
from typing import Optional, List

import numpy as np
from fastapi import FastAPI, HTTPException, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

os.environ["OMP_NUM_THREADS"] = "24"

from openvino import Core
from transformers import AutoProcessor, AutoTokenizer
from optimum.intel.openvino import OVModelForSpeechSeq2Seq


MODEL_DIR = os.getenv("ASR_MODEL_DIR", "/models/asr/distil-whisper-large-v3-int8")
ENCODER_DEVICE = os.getenv("ASR_ENCODER_DEVICE", "GPU.0")
DECODER_DEVICE = os.getenv("ASR_DECODER_DEVICE", "CPU")

app = FastAPI(
    title="Intel ASR Service",
    version="1.0.0",
    description="Speech-to-Text on Intel iGPU (encoder) + CPU (decoder)",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TranscribeResponse(BaseModel):
    text: str
    language: Optional[str]
    duration_sec: float
    processing_time_ms: float
    model: str
    encoder_device: str
    decoder_device: str


class HealthResponse(BaseModel):
    status: str
    model: str
    encoder_device: str
    decoder_device: str
    model_loaded: bool
    available_devices: List[str]


core = Core()
encoder_compiled = None
decoder_compiled = None
processor = None
tokenizer = None
model_loaded = False
load_error: Optional[str] = None


def load_model():
    global encoder_compiled, decoder_compiled, processor, tokenizer, model_loaded, load_error
    
    model_path = Path(MODEL_DIR)
    if not model_path.exists():
        load_error = f"Model not found at {model_path}"
        print(f"ERROR: {load_error}")
        return
    
    try:
        print(f"Loading ASR model from {MODEL_DIR}...")
        
        # Load processor (feature extractor + tokenizer)
        processor = AutoProcessor.from_pretrained(MODEL_DIR)
        tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR)
        
        # Load OpenVINO model
        ov_model = OVModelForSpeechSeq2Seq.from_pretrained(
            MODEL_DIR,
            compile=False,
        )
        
        # Compile encoder for iGPU, decoder for CPU
        print(f"Compiling encoder for {ENCODER_DEVICE}...")
        encoder_compiled = core.compile_model(ov_model.encoder, ENCODER_DEVICE)
        
        print(f"Compiling decoder for {DECODER_DEVICE}...")
        decoder_compiled = core.compile_model(ov_model.decoder, DECODER_DEVICE)
        
        # Warmup
        dummy_audio = np.zeros((1, 16000), dtype=np.float32)  # 1 sec silence
        inputs = processor(dummy_audio, sampling_rate=16000, return_tensors="np")
        encoder_inputs = {"input_features": inputs.input_features}
        _ = encoder_compiled(encoder_inputs)
        
        model_loaded = True
        load_error = None
        print(f"ASR model loaded: encoder->{ENCODER_DEVICE}, decoder->{DECODER_DEVICE}")
        
    except Exception as e:
        load_error = str(e)
        print(f"ASR model load failed: {e}")


@app.on_event("startup")
async def startup():
    load_model()


def generate_decode(input_features: np.ndarray, max_new_tokens: int = 448) -> str:
    """Run encoder + autoregressive decoder."""
    # Encode
    encoder_result = encoder_compiled({"input_features": input_features})
    encoder_hidden = encoder_result[encoder_compiled.output(0)]
    
    # Decoder autoregressive loop
    decoder_input_ids = np.array([[tokenizer.bos_token_id]], dtype=np.int64)
    
    generated_ids = []
    for _ in range(max_new_tokens):
        decoder_result = decoder_compiled({
            "input_ids": decoder_input_ids,
            "encoder_hidden_states": encoder_hidden,
        })
        logits = decoder_result[decoder_compiled.output(0)]
        next_token = np.argmax(logits[0, -1, :])
        
        if next_token == tokenizer.eos_token_id:
            break
            
        generated_ids.append(int(next_token))
        decoder_input_ids = np.append(decoder_input_ids, [[next_token]], axis=1)
    
    return tokenizer.decode(generated_ids, skip_special_tokens=True)


@app.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(
    file: UploadFile = File(...),
    language: Optional[str] = Form(None),
    task: str = Form("transcribe"),
):
    if load_error:
        raise HTTPException(status_code=500, detail=f"Model load failed: {load_error}")
    if not model_loaded:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    start_time = time.perf_counter()
    
    # Save uploaded file temporarily
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name
    
    try:
        # Load audio with processor
        import librosa
        audio, sr = librosa.load(tmp_path, sr=16000, mono=True)
        duration = len(audio) / sr
        
        inputs = processor(audio, sampling_rate=16000, return_tensors="np")
        
        # Run inference
        text = generate_decode(inputs.input_features)
        
        processing_time = (time.perf_counter() - start_time) * 1000
        
        return TranscribeResponse(
            text=text,
            language=language,
            duration_sec=duration,
            processing_time_ms=processing_time,
            model="distil-whisper-large-v3-int8",
            encoder_device=ENCODER_DEVICE,
            decoder_device=DECODER_DEVICE,
        )
    finally:
        os.unlink(tmp_path)


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(
        status="healthy" if load_error is None else "degraded",
        model="distil-whisper-large-v3-int8",
        encoder_device=ENCODER_DEVICE,
        decoder_device=DECODER_DEVICE,
        model_loaded=model_loaded,
        available_devices=core.available_devices,
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8002"))
    uvicorn.run(app, host="0.0.0.0", port=port)
