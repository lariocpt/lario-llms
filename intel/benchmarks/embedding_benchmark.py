#!/usr/bin/env python3
"""
Embedding Benchmark — NPU/GPU.0/CPU comparison for BGE-M3, Nomic, E5-Mistral
"""

import os
import time
import json
import argparse
import numpy as np
from pathlib import Path

os.environ["OMP_NUM_THREADS"] = "24"

from openvino import Core
from transformers import AutoTokenizer


MODELS = {
    "bge-m3-int8": {
        "path": "intel/models/embeddings/bge-m3-int8",
        "dim": 1024,
        "batch_sizes": [1, 8, 32, 64],
        "seq_len": 512,
    },
    "nomic-embed-v1.5-int8": {
        "path": "intel/models/embeddings/nomic-embed-v1.5-int8",
        "dim": 768,
        "batch_sizes": [1, 8, 32, 64],
        "seq_len": 512,
    },
    "e5-mistral-7b-int4": {
        "path": "intel/models/embeddings/e5-mistral-7b-int4",
        "dim": 4096,
        "batch_sizes": [1, 4, 8, 16],
        "seq_len": 512,
    },
}

DEVICES = ["NPU", "GPU.0", "CPU"]
TEST_PROMPTS = [
    "This is a test sentence for embedding benchmark.",
    "The quick brown fox jumps over the lazy dog.",
    "OpenVINO enables high-performance inference on Intel hardware.",
    "Embeddings are vector representations of text.",
] * 16  # 64 sentences


def benchmark_model(model_name: str, device: str, batch_size: int, seq_len: int, iterations: int = 50) -> dict:
    """Run benchmark for a model on a specific device."""
    model_config = MODELS[model_name]
    model_path = Path(model_config["path"]) / "openvino_model.xml"
    
    if not model_path.exists():
        return {"error": f"Model not found: {model_path}"}
    
    try:
        core = Core()
        if device not in core.available_devices:
            return {"error": f"Device {device} not available"}
        
        compiled = core.compile_model(str(model_path), device)
        tokenizer = AutoTokenizer.from_pretrained(model_config["path"])
        
        # Prepare inputs
        texts = TEST_PROMPTS[:batch_size]
        inputs = tokenizer(texts, padding="max_length", truncation=True, max_length=seq_len, return_tensors="np")
        
        # Warmup
        for _ in range(5):
            _ = compiled(inputs)
        
        # Benchmark
        latencies = []
        for _ in range(iterations):
            start = time.perf_counter()
            result = compiled(inputs)
            elapsed = time.perf_counter() - start
            latencies.append(elapsed)
        
        latencies = np.array(latencies) * 1000  # ms
        throughput = (batch_size / np.mean(latencies / 1000))
        
        return {
            "model": model_name,
            "device": device,
            "batch_size": batch_size,
            "seq_len": seq_len,
            "iterations": iterations,
            "avg_latency_ms": float(np.mean(latencies)),
            "std_latency_ms": float(np.std(latencies)),
            "p50_latency_ms": float(np.percentile(latencies, 50)),
            "p95_latency_ms": float(np.percentile(latencies, 95)),
            "p99_latency_ms": float(np.percentile(latencies, 99)),
            "throughput_vec_s": float(throughput),
            "output_dim": model_config["dim"],
        }
        
    except Exception as e:
        return {"error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Embedding benchmark")
    parser.add_argument("--models", nargs="+", default=list(MODELS.keys()), help="Models to benchmark")
    parser.add_argument("--devices", nargs="+", default=DEVICES, help="Devices to test")
    parser.add_argument("--iterations", type=int, default=50, help="Iterations per test")
    parser.add_argument("--output", help="Output JSON file")
    args = parser.parse_args()
    
    core = Core()
    available_devices = [d for d in args.devices if d in core.available_devices]
    print(f"Available devices: {available_devices}")
    print(f"Models: {args.models}")
    print("=" * 80)
    
    results = []
    
    for model_name in args.models:
        if model_name not in MODELS:
            print(f"Unknown model: {model_name}")
            continue
        
        model_config = MODELS[model_name]
        for device in available_devices:
            for batch_size in model_config["batch_sizes"]:
                print(f"\nTesting {model_name} on {device} (batch={batch_size})...")
                result = benchmark_model(model_name, device, batch_size, model_config["seq_len"], args.iterations)
                
                if "error" in result:
                    print(f"  ERROR: {result['error']}")
                else:
                    print(f"  Avg: {result['avg_latency_ms']:.2f} ms, "
                          f"P95: {result['p95_latency_ms']:.2f} ms, "
                          f"Throughput: {result['throughput_vec_s']:.1f} vec/s")
                
                results.append(result)
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    for r in results:
        if "error" in r:
            print(f"  {r.get('model', '?')} @ {r.get('device', '?')}: ERROR - {r['error']}")
        else:
            print(f"  {r['model']} @ {r['device']} (bs={r['batch_size']}): "
                  f"{r['throughput_vec_s']:.1f} vec/s, P95={r['p95_latency_ms']:.1f} ms")
    
    if args.output:
        with open(args.output, "w") as f:
            json.dump({
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "models": args.models,
                "devices": available_devices,
                "results": results,
            }, f, indent=2)
        print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()
