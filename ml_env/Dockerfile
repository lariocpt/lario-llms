# Start from the official ROCm PyTorch image which is optimized for AMD GPUs
FROM rocm/pytorch:rocm6.1_ubuntu22.04_py3.10

# Set the working directory
WORKDIR /app

# Install system dependencies (ffmpeg for Whisper)
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Install the machine learning tools
RUN pip install --no-cache-dir openai-whisper emm sentence-transformers diffusers transformers accelerate

# The container will run indefinitely using the command in docker-compose.yml
