#!/usr/bin/env python3
"""Export the existing BGE-M3 weights without changing its embedding space."""
import os
from pathlib import Path
os.environ.setdefault('HF_HOME', '/mnt/xfs/AI_Models/huggingface')
from optimum.intel.openvino import OVModelForFeatureExtraction
from transformers import AutoTokenizer
from openvino_tokenizers import convert_tokenizer
import openvino as ov

out = Path('/mnt/xfs/AI_Models/openvino/embeddings/bge-m3-fp16')
out.mkdir(parents=True, exist_ok=True)
model = OVModelForFeatureExtraction.from_pretrained('BAAI/bge-m3', export=True, compile=False, load_in_8bit=False, local_files_only=True)
model.save_pretrained(out)
tokenizer = AutoTokenizer.from_pretrained('BAAI/bge-m3', local_files_only=True)
tokenizer.save_pretrained(out)
ov.save_model(convert_tokenizer(tokenizer), out/'openvino_tokenizer.xml')
print(out, flush=True)
