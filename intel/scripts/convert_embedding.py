#!/usr/bin/env python3
"""
Convert HuggingFace embedding models to OpenVINO IR with INT8 quantization.
Target: NPU (primary) -> GPU.0 -> CPU
"""

import os
import argparse
from pathlib import Path

os.environ["OMP_NUM_THREADS"] = "24"

from optimum.intel.openvino import OVModelForFeatureExtraction
from transformers import AutoTokenizer
import openvino as ov
import nncf


MODEL_CONFIGS = {
    "bge-m3": {
        "model_id": "BAAI/bge-m3",
        "output_dir": "intel/models/embeddings/bge-m3-int8",
        "description": "Multi-lingual, 567M params, supports retrieval/classification/clustering",
    },
    "nomic-v1.5": {
        "model_id": "nomic-ai/nomic-embed-text-v1.5",
        "output_dir": "intel/models/embeddings/nomic-embed-v1.5-int8",
        "description": "137M params, long context (8192), MIT license",
    },
    "e5-mistral-7b": {
        "model_id": "intfloat/e5-mistral-7b-instruct",
        "output_dir": "intel/models/embeddings/e5-mistral-7b-int4",
        "description": "7B params, INT4 quantization, high quality fallback",
        "quantization": "int4",
    },
}


def convert_model(model_key: str, device: str = "NPU", batch_size: int = 32, seq_len: int = 512):
    config = MODEL_CONFIGS[model_key]
    model_id = config["model_id"]
    output_dir = Path(config["output_dir"])
    quant_mode = config.get("quantization", "int8")
    
    print(f"\n{'='*60}")
    print(f"Converting {model_key}: {model_id}")
    print(f"Output: {output_dir}")
    print(f"Quantization: {quant_mode.upper()}")
    print(f"{'='*60}")
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Loading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
    tokenizer.save_pretrained(output_dir)
    
    print(f"Exporting to OpenVINO IR...")
    ov_model = OVModelForFeatureExtraction.from_pretrained(
        model_id,
        export=True,
        compile=False,
        load_in_8bit=(quant_mode == "int8"),
        trust_remote_code=True,
    )
    
    ov_model.save_pretrained(output_dir)
    print(f"Saved model to {output_dir}")
    
    if quant_mode == "int4":
        print(f"Applying NNCF INT4 weight-only quantization...")
        core = ov.Core()
        model_path = output_dir / "openvino_model.xml"
        model = core.read_model(model_path)
        
        def transform_fn(data_item):
            inputs = tokenizer(
                data_item["text"],
                padding="max_length",
                truncation=True,
                max_length=seq_len,
                return_tensors="np",
            )
            return inputs
        
        from datasets import load_dataset
        calib_dataset = load_dataset("wikitext", "wikitext-2-raw-v1", split="train[:100]")
        calib_dataset = calib_dataset.map(lambda x: {"text": x["text"]})
        
        quantized_model = nncf.quantize(
            model,
            calibration_dataset=nncf.Dataset(calib_dataset, transform_fn),
            mode=nncf.QuantizationMode.INT4_ASYM,
            subset_size=50,
        )
        
        ov.save_model(quantized_model, model_path)
        print(f"Saved INT4 quantized model")
    
    # Verify compilation
    print(f"Compiling for {device} to verify...")
    core = ov.Core()
    try:
        compiled = core.compile_model(str(output_dir / "openvino_model.xml"), device)
        print(f"Successfully compiled for {device}")
        
        test_text = "This is a test sentence for embedding."
        inputs = tokenizer(test_text, return_tensors="np", padding=True, truncation=True, max_length=seq_len)
        # Convert BatchEncoding to dict
        input_dict = dict(inputs)
        result = compiled(input_dict)
        embeddings = result[compiled.output(0)]
        print(f"Test inference: output shape {embeddings.shape}")
        
    except Exception as e:
        print(f"Compilation failed for {device}: {e}")
        print(f"  Will fall back to CPU at runtime")
    
    print(f"\n{model_key} conversion complete!")
    return output_dir


def benchmark_model(model_dir: str, device: str = "NPU", batch_size: int = 32, seq_len: int = 128, iterations: int = 100):
    import time
    import numpy as np
    from transformers import AutoTokenizer
    
    print(f"\nBenchmarking {model_dir} on {device}...")
    
    core = ov.Core()
    compiled = core.compile_model(str(Path(model_dir) / "openvino_model.xml"), device)
    tokenizer = AutoTokenizer.from_pretrained(model_dir)
    
    test_texts = ["This is a benchmark sentence for embedding performance testing."] * batch_size
    inputs = tokenizer(test_texts, padding="max_length", truncation=True, max_length=seq_len, return_tensors="np")
    input_dict = dict(inputs)
    
    for _ in range(5):
        _ = compiled(input_dict)
    
    latencies = []
    for _ in range(iterations):
        start = time.perf_counter()
        result = compiled(input_dict)
        elapsed = time.perf_counter() - start
        latencies.append(elapsed)
    
    avg_latency = np.mean(latencies) * 1000
    std_latency = np.std(latencies) * 1000
    throughput = (batch_size / np.mean(latencies))
    
    print(f"  Batch size: {batch_size}, Seq len: {seq_len}")
    print(f"  Avg latency: {avg_latency:.2f} +- {std_latency:.2f} ms")
    print(f"  Throughput: {throughput:.1f} vectors/sec")
    print(f"  P95 latency: {np.percentile(latencies, 95) * 1000:.2f} ms")
    
    return {
        "device": device,
        "batch_size": batch_size,
        "seq_len": seq_len,
        "avg_latency_ms": avg_latency,
        "std_latency_ms": std_latency,
        "throughput_vec_s": throughput,
    }


def main():
    parser = argparse.ArgumentParser(description="Convert embedding models to OpenVINO")
    parser.add_argument("model", choices=list(MODEL_CONFIGS.keys()) + ["all"], help="Model to convert")
    parser.add_argument("--device", default="NPU", choices=["NPU", "GPU.0", "CPU"], help="Target device")
    parser.add_argument("--batch-size", type=int, default=32, help="Batch size for benchmark")
    parser.add_argument("--seq-len", type=int, default=512, help="Sequence length")
    parser.add_argument("--benchmark", action="store_true", help="Run benchmark after conversion")
    parser.add_argument("--iterations", type=int, default=100, help="Benchmark iterations")
    args = parser.parse_args()
    
    models_to_convert = list(MODEL_CONFIGS.keys()) if args.model == "all" else [args.model]
    
    for model_key in models_to_convert:
        output_dir = convert_model(model_key, device=args.device, batch_size=args.batch_size, seq_len=args.seq_len)
        
        if args.benchmark:
            core = ov.Core()
            for dev in ["NPU", "GPU.0", "CPU"]:
                if dev in core.available_devices:
                    try:
                        benchmark_model(str(output_dir), device=dev, batch_size=args.batch_size, seq_len=args.seq_len, iterations=args.iterations)
                    except Exception as e:
                        print(f"  Benchmark failed on {dev}: {e}")


if __name__ == "__main__":
    main()
