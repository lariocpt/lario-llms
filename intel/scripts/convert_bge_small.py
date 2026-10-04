#!/usr/bin/env python3
"""Convert BGE-small-en-v1.5 to OpenVINO INT8"""

import os
os.environ["OMP_NUM_THREADS"] = "24"

from optimum.intel.openvino import OVModelForFeatureExtraction
from transformers import AutoTokenizer
from pathlib import Path

MODEL_ID = "BAAI/bge-small-en-v1.5"
OUTPUT_DIR = Path("/home/lario/Projects/personal/lario-llms/intel/models/embeddings/bge-small-en-v1.5-int8")

print(f"Converting {MODEL_ID}...")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
tokenizer.save_pretrained(OUTPUT_DIR)

ov_model = OVModelForFeatureExtraction.from_pretrained(
    MODEL_ID,
    export=True,
    compile=False,
    load_in_8bit=True,
    trust_remote_code=True,
)

ov_model.save_pretrained(OUTPUT_DIR)
print(f"Saved to {OUTPUT_DIR}")

from openvino import Core
core = Core()
for device in ["NPU", "GPU.0", "CPU"]:
    if device in core.available_devices:
        try:
            compiled = core.compile_model(str(OUTPUT_DIR / "openvino_model.xml"), device)
            print(f"✓ Compiled for {device}")
        except Exception as e:
            print(f"✗ {device}: {e}")

print("Done!")
