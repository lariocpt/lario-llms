#!/usr/bin/env python3
"""
Intel TTS Service - Kokoro-82M / Piper on iGPU
Placeholder - to be implemented in Phase 4
"""

import os
import base64
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import uvicorn

app = FastAPI(
    title="Intel TTS Service",
    version="1.0.0",
    description="Text-to-Speech on Intel iGPU (placeholder)",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SynthesizeRequest(BaseModel):
    text: str
    voice: Optional[str] = "default"
    format: str = "wav"  # wav, mp3


class SynthesizeResponse(BaseModel):
    audio_base64: str
    format: str
    sample_rate: int
    voice: str
    model: str
    device: str


class VoicesResponse(BaseModel):
    voices: List[dict]


class HealthResponse(BaseModel):
    status: str
    model: str
    device: str
    model_loaded: bool


@app.post("/synthesize", response_model=SynthesizeResponse)
async def synthesize(req: SynthesizeRequest):
    raise HTTPException(status_code=501, detail="Not implemented - Phase 4")


@app.get("/voices", response_model=VoicesResponse)
async def voices():
    return VoicesResponse(
        voices=[
            {"id": "default", "name": "Default", "language": "en"},
            {"id": "af_heart", "name": "af_heart", "language": "en"},
            {"id": "am_puck", "name": "am_puck", "language": "en"},
        ]
    )


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(
        status="not_implemented",
        model="kokoro-82m-int8",
        device="GPU.0",
        model_loaded=False,
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8004"))
    uvicorn.run(app, host="0.0.0.0", port=port)
