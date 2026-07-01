# llamacpp — Dockerized llama.cpp + llama-swap, GPU via AMD ROCm (Strix Halo / gfx1151).
# Replaces the old `ollama` container. Self-contained: bundles the validated llama.cpp
# build (b9842) + Ollama's ROCm 7.2.1 runtime, so the host copies can be deleted afterwards.
# Staged into vendor/ by build.sh (gitignored). See docs/strix_halo_fedora_setup.md.
FROM ubuntu:24.04

RUN apt-get update && apt-get install -y --no-install-recommends \
      libgomp1 ca-certificates curl tini \
    && rm -rf /var/lib/apt/lists/*

# llama.cpp binaries + shared libs (validated build b9842: llama-server, llama-cli, llama-quantize, …)
COPY vendor/llama/  /opt/llama/
# Ollama's bundled ROCm 7.2.1 runtime (libamdhip64.so.7, librocblas.so.5, libhipblas.so.3,
# rocblas/library/*.hsaco tensile kernels incl. gfx1102/gfx1150, …)
COPY vendor/rocm/   /opt/rocm-ollama/
# llama-swap proxy (multi-model, on-demand load/unload, OpenAI + Ollama compatible)
COPY vendor/llama-swap /usr/local/bin/llama-swap

RUN chmod +x /usr/local/bin/llama-swap

ENV PATH="/opt/llama:${PATH}" \
    LD_LIBRARY_PATH="/opt/llama:/opt/rocm-ollama" \
    HSA_OVERRIDE_GFX_VERSION=11.0.2 \
    ROCBLAS_TENSILE_LIBPATH=/opt/rocm-ollama/rocblas/library \
    HF_HOME=/root/.cache/huggingface

EXPOSE 11434
# tini reaps the llama-server children that llama-swap spawns.
ENTRYPOINT ["tini","--"]
CMD ["llama-swap","-config","/config/config.yaml","-listen",":11434"]
