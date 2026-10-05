#!/usr/bin/env python3
"""
OpenVINO GenAI Benchmark — NPU/GPU/CPU inference comparison
Tests Qwen3.8-Flash-Next on NPU, GPU (XMX), and CPU backends.
"""

import os
import time
import json
import argparse
from pathlib import Path

# Set OpenMP threads
os.environ["OMP_NUM_THREADS"] = os.getenv("OMP_NUM_THREADS", "24")

MODEL_PATH = os.getenv("MODEL_PATH", "/models/gguf/qwen38-flash/Qwen3.8-Flash-Next-UD-Q3_K_XL-00001-of-00003.gguf")
DEVICES = ["NPU", "GPU.0", "CPU"]
PROMPTS = [
    "Write a short haiku about a lighthouse.",
    "Explain quantum computing in simple terms.",
    "Write a Python function to merge two sorted lists.",
]

def benchmark_device(device: str, prompt: str, max_tokens: int = 200) -> dict:
    """Run inference on specified device and return metrics."""
    try:
        from openvino_genai import LLMPipeline
        
        print(f"\n=== Testing {device} ===")
        pipe = LLMPipeline(MODEL_PATH, device=device)
        
        # Warmup
        _ = pipe.generate("Warmup.", max_new_tokens=10)
        
        results = []
        for prompt in PROMPTS:
            start = time.perf_counter()
            result = pipe.generate(
                prompt,
                max_new_tokens=200,
                temperature=0.7,
                top_p=0.95,
                top_k=50,
                do_sample=True,
            )
            elapsed = time.perf_counter() - start
            
            tokens = len(result.split())
            tok_s = tokens / elapsed if elapsed > 0 else 0
            
            results.append({
                "prompt": prompt[:50] + "...",
                "tokens": tokens,
                "time_sec": round(elapsed, 3),
                "tok_s": round(tok_s, 2)
            })
            print(f"  {device}: {tokens} tokens in {elapsed:.2f}s = {tok_s:.1f} tok/s")
        
        avg_tok_s = sum(r["tok_s"] for r in results) / len(results)
        return {
            "device": device,
            "avg_tok_s": round(avg_tok_s, 2),
            "results": results
        }
        
    except Exception as e:
        print(f"  {device}: FAILED - {e}")
        return {"device": device, "error": str(e)}

def main():
    parser = argparse.ArgumentParser(description="OpenVINO GenAI benchmark")
    parser.add_argument("--devices", nargs="+", default=["NPU", "GPU.0", "CPU"],
                        help="Devices to test (NPU, GPU.0, CPU)")
    parser.add_argument("--tokens", type=int, default=200, help="Max tokens per generation")
    parser.add_argument("--output", help="Output JSON file")
    args = parser.parse_args()
    
    print(f"Model: {MODEL_PATH}")
    print(f"Devices: {args.devices}")
    print(f"Tokens per generation: {args.tokens}")
    print("=" * 60)
    
    results = []
    for device in args.devices:
        result = benchmark_device(device, PROMPTS[0], args.tokens)
        results.append(result)
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for r in results:
        if "error" in r:
            print(f"  {r['device']}: ERROR - {r['error']}")
        else:
            print(f"  {r['device']}: {r['avg_tok_s']:.1f} tok/s avg")
    
    if args.output:
        with open(args.output, "w") as f:
            json.dump({
                "model": MODEL_PATH,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "results": results
            }, f, indent=2)
        print(f"\nResults saved to {args.output}")

if __name__ == "__main__":
    main()
