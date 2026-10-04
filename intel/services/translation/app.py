#!/usr/bin/env python3
"""
Intel Translation Service - NLLB-200-Distilled-600M on NPU
Placeholder - to be implemented in Phase 3
"""

import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import uvicorn

app = FastAPI(
    title="Intel Translation Service",
    version="1.0.0",
    description="Translation on Intel NPU (placeholder)",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TranslateRequest(BaseModel):
    text: str
    source_lang: str = "eng_Latn"
    target_lang: str = "spa_Latn"


class TranslateResponse(BaseModel):
    translated_text: str
    source_lang: str
    target_lang: str
    model: str
    device: str


class BatchTranslateRequest(BaseModel):
    texts: List[str]
    source_lang: str = "eng_Latn"
    target_lang: str = "spa_Latn"


class BatchTranslateResponse(BaseModel):
    translations: List[str]
    source_lang: str
    target_lang: str
    model: str
    device: str


class HealthResponse(BaseModel):
    status: str
    model: str
    device: str
    model_loaded: bool


@app.post("/translate", response_model=TranslateResponse)
async def translate(req: TranslateRequest):
    raise HTTPException(status_code=501, detail="Not implemented - Phase 3")


@app.post("/translate/batch", response_model=BatchTranslateResponse)
async def translate_batch(req: BatchTranslateRequest):
    raise HTTPException(status_code=501, detail="Not implemented - Phase 3")


@app.get("/languages")
async def languages():
    return {
        "languages": [
            {"code": "eng_Latn", "name": "English"},
            {"code": "spa_Latn", "name": "Spanish"},
            {"code": "fra_Latn", "name": "French"},
            {"code": "deu_Latn", "name": "German"},
            {"code": "zho_Hans", "name": "Chinese (Simplified)"},
            {"code": "jpn_Jpan", "name": "Japanese"},
            {"code": "kor_Kore", "name": "Korean"},
            {"code": "rus_Cyrl", "name": "Russian"},
            {"code": "ara_Arab", "name": "Arabic"},
            {"code": "hin_Deva", "name": "Hindi"},
        ],
        "total": 200,
    }


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(
        status="not_implemented",
        model="nllb-200-distilled-600m-int8",
        device="NPU",
        model_loaded=False,
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8003"))
    uvicorn.run(app, host="0.0.0.0", port=port)
