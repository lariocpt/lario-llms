# ipex_server/app.py — FastAPI wrapper for Intel Extension for PyTorch (IPEX) + XPU
# Provides /generate endpoint with Intel optimizations (AVX-VNNI, XMX, NPU offload)

import os
import torch
import intel_extension_for_pytorch as ipex
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import uvicorn

app = FastAPI(title="IPEX Server", version="1.0.0")

# Device setup
device = torch.device("xpu" if torch.xpu.is_available() else "cpu")
print(f"IPEX Server starting on device: {device}")
print(f"XPU available: {torch.xpu.is_available()}")
if torch.xpu.is_available():
    print(f"XPU device count: {torch.xpu.device_count()}")

class GenerateRequest(BaseModel):
    prompt: str
    max_tokens: int = 200
    temperature: float = 0.7
    top_p: float = 0.95
    top_k: int = 50
    stream: bool = False

class GenerateResponse(BaseModel):
    text: str
    tokens_generated: int
    device: str

# Load model on startup (lazy load)
model = None
tokenizer = None
model_name = os.getenv("MODEL_NAME", "unsloth/Qwen3.8-Flash-Next-GGUF:UD-Q3_K_XL")

@app.on_event("startup")
async def load_model():
    global model, tokenizer
    try:
        from transformers import AutoModelForCausalLM, AutoTokenizer
        import intel_extension_for_pytorch as ipex
        
        print(f"Loading model: {model_name}")
        tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(
            model_name,
            torch_dtype=torch.bfloat16,
            low_cpu_mem_usage=True,
            device_map="auto" if torch.xpu.is_available() else "cpu",
        )
        
        if torch.xpu.is_available():
            model = ipex.optimize(model, dtype=torch.bfloat16, inplace=True)
            model = model.to("xpu")
        
        model.eval()
        print(f"Model loaded on {device}")
    except Exception as e:
        print(f"Model load failed: {e}")
        # Fallback to CPU
        device = torch.device("cpu")

@app.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest):
    if model is None or tokenizer is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    inputs = tokenizer(req.prompt, return_tensors="pt").to(device)
    
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=req.max_tokens,
            temperature=req.temperature,
            top_p=req.top_p,
            top_k=req.top_k,
            do_sample=req.temperature > 0,
            pad_token_id=tokenizer.eos_token_id,
        )
    
    generated = outputs[0][inputs.input_ids.shape[1]:]
    text = tokenizer.decode(generated, skip_special_tokens=True)
    
    return GenerateResponse(
        text=text,
        tokens_generated=len(generated),
        device=str(device)
    )

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "device": str(device),
        "model_loaded": model is not None,
        "xpu_available": torch.xpu.is_available()
    }

@app.get("/models")
async def list_models():
    return {"models": [model_name], "default": model_name}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8081)
