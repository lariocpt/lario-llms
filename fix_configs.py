import re

def fix_config(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    # Qwen 72B
    content = content.replace("qwen2.5-72b-instruct.gguf", "Qwen2.5-72B-Instruct-Q4_K_M.gguf")
    # Llama Vision
    content = content.replace("llama-3.2-11b-vision-instruct.gguf", "Llama-3.2-11B-Vision-Instruct.Q4_K_M.gguf")
    # Llama Vision mmproj
    content = content.replace("llama-3.2-11b-vision-mmproj.gguf", "Llama-3.2-11B-Vision-Instruct-mmproj.f16.gguf")
    # Gemma 3 Vision
    content = content.replace("gemma-3-12b-it.gguf", "gemma-3-12b-it-Q4_K_M.gguf")
    content = content.replace("gemma-3-12b-mmproj.gguf", "gemma-3-12b-it-mmproj-F16.gguf")
    # Qwen VL
    content = content.replace("qwen2.5-vl-7b-instruct.gguf", "Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf")
    content = content.replace("qwen2.5-vl-mmproj.gguf", "Qwen2.5-VL-7B-Instruct-mmproj-F16.gguf")

    with open(filepath, 'w') as f:
        f.write(content)

fix_config("/mnt/Shared/personal/lario-llms/windows-setup/config-max.yaml")
fix_config("/mnt/Shared/personal/lario-llms/windows-setup/config-fast.yaml")
fix_config("/mnt/Shared/personal/lario-llms/windows-setup/config.yaml")
