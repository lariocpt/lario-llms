# 🎮 AMD Strix Halo (Radeon 8060S) Fedora Setup & Replication Guide

This guide documents the exact steps required to replicate the AMD Strix Halo (Radeon 8060S / Ryzen AI 9) graphics drivers, ROCm libraries, merged Ollama binaries, and Python ML matching environment on a fresh Fedora installation.

---

## 🖥️ 1. Host Graphics & Mesa Driver Setup

Because the Strix Halo utilizes the new **RDNA 3.5** integrated graphics architecture:
*   **Kernel Compatibility**: Requires Kernel 6.10 or newer (Fedora 44+ runs Kernel 7.0+ natively, which has out-of-the-box support).
*   **Mesa Drivers**: Make sure you have the latest Mesa graphics acceleration packages installed:
    ```bash
    sudo dnf upgrade -y mesa-dri-drivers mesa-vulkan-drivers mesa-va-drivers
    ```
*   **VRAM Configuration (UMA)**: For machine learning work, configure the UMA Frame Buffer Size in your system BIOS to allocate **64 GB** (or half of your system RAM) as dedicated VRAM.

---

## 🧠 2. The Ollama ROCm Overlay Merge Hack

The default AMD ROCm-specific Ollama build (`ollama-linux-amd64-rocm.tar.zst`) acts as a partial overlay and is **missing** the core `libggml-base.so` shared library. If run on its own, it will fail to start. You must merge the standard Linux package with the ROCm package:

### Steps:
1. **Download both packages**:
    ```bash
    # Standard Linux package (provides libggml-base)
    wget https://ollama.com/download/ollama-linux-amd64.tar.zst
    
    # ROCm package (provides HIP/GPU acceleration)
    wget https://ollama.com/download/ollama-linux-amd64-rocm.tar.zst
    ```
2. **Extract standard package**:
    ```bash
    tar -xf ollama-linux-amd64.tar.zst -C ~/.local
    ```
3. **Extract ROCm package over it** (overwriting files and placing libraries in the ROCm directory):
    ```bash
    tar -xf ollama-linux-amd64-rocm.tar.zst -C ~/.local
    ```
4. **Force ROCm GPU Detection**:
    Since the Radeon 8060S (GFX1150/GFX1151) is very new, ROCm does not recognize it natively yet. You must set the environment variable override to treat it as a supported RDNA3 card:
    ```bash
    export HSA_OVERRIDE_GFX_VERSION=11.0.2
    ```
    Add this to your `~/.zshrc`, `~/.bashrc`, or systemd service environment (`Environment="HSA_OVERRIDE_GFX_VERSION=11.0.2"`).

---

## 🐍 3. Python ML & Pandas/EMM Environment Setup

The ML pipeline utilizes **Micromamba** to handle Python versions in user-space and installs PyTorch compiled for ROCm alongside **ING Wholesale Banking's Entity Matching Model (EMM)** which utilizes pandas.

### Setup Environment:
1. **Install Micromamba**:
    ```bash
    curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xvj bin/micromamba
    mkdir -p ~/.local/bin
    mv bin/micromamba ~/.local/bin/
    rm -rf bin
    ```
2. **Create Python 3.12 Environment**:
    ```bash
    export MAMBA_ROOT_PREFIX=~/.micromamba
    ~/.local/bin/micromamba create -n ml_env python=3.12 -c conda-forge -y
    ```
3. **Install PyTorch with ROCm 6.1 Support**:
    ```bash
    ~/.local/bin/micromamba run -n ml_env pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm6.1
    ```
4. **Install Pandas, EMM, and ML Packages**:
    ```bash
    ~/.local/bin/micromamba run -n ml_env pip install pandas openai-whisper emm sentence-transformers diffusers accelerate transformers
    ```

---

## 🐳 4. Docker GPU Passthrough Config

To allow your Docker containers (like the core AI stack and dev containers) to access your Strix Halo GPU, configure device mount mappings in your `docker-compose.override.yml`:

```yaml
services:
  ollama:
    devices:
      - /dev/kfd:/dev/kfd
      - /dev/dri:/dev/dri
    environment:
      - HSA_OVERRIDE_GFX_VERSION=11.0.2
```

Ensure your user account is in the `docker` group:
```bash
sudo usermod -aG docker $USER
newgrp docker
```
> [!NOTE]
> If running Docker from a systemd user session, enable lingering:
> `loginctl enable-linger $USER`
