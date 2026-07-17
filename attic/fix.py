import os
import glob

replacements = {
    "-hf unsloth/gemma-4-31B-it-GGUF:BF16": "-m models\\gemma-4-31b-it-Q8_0.gguf",
    "-hf unsloth/Qwen3.6-27B-GGUF:UD-Q4_K_XL": "-m models\\qwen3.6-27b.gguf",
    "-hf unsloth/Qwen2.5-VL-7B-Instruct-GGUF:Q4_K_M": "-m models\\qwen2.5-vl-7b-instruct.gguf",
    "--mmproj /root/.cache/huggingface/mmproj/qwen2.5-vl-mmproj.f16.gguf": "--mmproj models\\qwen2.5-vl-mmproj.gguf",
    "-hf unsloth/gemma-3-12b-it-GGUF:Q4_K_M": "-m models\\gemma-3-12b-it.gguf",
    "--mmproj /root/.cache/huggingface/mmproj/gemma-3-12b-mmproj.f16.gguf": "--mmproj models\\gemma-3-12b-mmproj.gguf",
    "-hf bartowski/Qwen2.5-72B-Instruct-GGUF:Qwen2.5-72B-Instruct-Q4_K_M.gguf": "-m models\\qwen2.5-72b-instruct.gguf",
    "-hf leafspark/Llama-3.2-11B-Vision-Instruct-GGUF:Llama-3.2-11B-Vision-Instruct.Q4_K_M.gguf": "-m models\\llama-3.2-11b-vision-instruct.gguf",
    "--mmproj leafspark/Llama-3.2-11B-Vision-Instruct-GGUF:Llama-3.2-11B-Vision-Instruct-mmproj.f16.gguf": "--mmproj models\\llama-3.2-11b-vision-mmproj.gguf",
    "-hf unsloth/MiniMax-M2.7-GGUF:UD-Q3_K_S": "-m models\\minimax-text-01-ud-q3_k_s.gguf"
}

for file in glob.glob("/mnt/Shared/personal/lario-llms/windows-setup/config*.yaml"):
    with open(file, "r") as f:
        content = f.read()
    
    for old, new in replacements.items():
        content = content.replace(old, new)
        
    with open(file, "w") as f:
        f.write(content)
        
print("Configs patched.")
