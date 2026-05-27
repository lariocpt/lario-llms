import torch
from diffusers import FluxPipeline
import argparse

parser = argparse.ArgumentParser(description="Generate an image using Flux.1-schnell on ROCm")
parser.add_argument("--prompt", type=str, default="A highly detailed futuristic city with glowing neon lights, cyberpunk style", help="The image prompt")
parser.add_argument("--output", type=str, default="output.png", help="The output image filename")
args = parser.parse_args()

print(f"Loading Flux.1-schnell on device: cuda (ROCm translates this to AMD GPU)...")

# Load the pipeline. Flux.1-schnell is relatively lightweight for this class of model.
# We load it in bfloat16 for speed and memory efficiency.
pipe = FluxPipeline.from_pretrained(
    "black-forest-labs/FLUX.1-schnell",
    torch_dtype=torch.bfloat16
)
# Move pipeline to GPU
pipe.enable_model_cpu_offload()

print(f"Generating image for prompt: '{args.prompt}'")
# Flux.1-schnell generates great images in just 4 inference steps
image = pipe(
    prompt=args.prompt,
    num_inference_steps=4,
    guidance_scale=0.0
).images[0]

image.save(args.output)
print(f"Success! Image saved to {args.output}")
