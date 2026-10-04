# Intel AI Stack for bigcachy

This directory contains the Intel-optimized AI stack components for the bigcachy host.

## Directory Structure

```
intel/
├── ipex_server/          # FastAPI wrapper for IPEX (CPU + XPU)
├── openvino_genai/       # FastAPI wrapper for OpenVINO GenAI (NPU/GPU)
├── benchmarks/           # Benchmark scripts for NPU/GPU/CPU comparison
├── README.md             # This file
└── llama-xmx-config.yaml # llama.cpp config for XMX GPU offload
```

## Quick Start

```bash
# Start the Intel AI stack (IPEX + OpenVINO + llama-xmx + monitoring)
cd ~/Projects/personal/lario-llms
docker compose -f docker-compose.yml -f docker-compose.bigcachy.yml -f docker-compose.intel.yml up -d

# Run benchmark
docker compose -f docker-compose.yml -f docker-compose.bigcachy.yml -f docker-compose.intel.yml \
  --profile benchmark up openvino-benchmark

# Check GPU/NPU utilization
watch -n1 'rocm-smi --showuse --showmemuse 2>/dev/null | grep -E "GPU|VRAM"'
# Or
open http://localhost:9090  # intel-gpu-monitor
```

## Services

| Service | Port | Description |
|---------|------|-------------|
| ipex-server | 8081 | IPEX (PyTorch + XPU/NPU) |
| openvino-genai | 8082 | OpenVINO GenAI (NPU/GPU/CPU) |
| llama-xmx | 8083 | llama.cpp with XMX GPU offload |
| intel-gpu-monitor | 9090 | Intel GPU/NPU telemetry |

## API Endpoints

### IPEX Server (port 8081)
```bash
# Generate
curl -X POST http://localhost:8081/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello", "max_tokens": 100}'

# Health
curl http://localhost:8081/health
```

### OpenVINO GenAI (port 8082)
```bash
# Generate
curl -X POST http://localhost:8082/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello", "max_tokens": 100}'

# Chat completions (OpenAI compatible)
curl -X POST http://localhost:8082/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello"}], "max_tokens": 100}'

# Health
curl http://localhost:8082/health
```

### llama-xmx (port 8083)
```bash
# Via llama-swap on lario-net
curl -X POST http://llama-xmx:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "agent", "messages": [{"role": "user", "content": "Hello"}], "max_tokens": 100}'
```

## Model Configuration

Models are read from `/mnt/xfs/AI_Models` (mounted read-only):
- `/mnt/xfs/AI_Models/gguf/qwen38-flash/` - Qwen3.8-Flash-Next UD-Q3_K_XL
- `/mnt/xfs/AI_Models/huggingface/` - HuggingFace cache

## Building llama-xmx (XMX offload)

```bash
cd ~/Projects/personal/lario-llms
docker compose -f docker-compose.yml -f docker-compose.bigcachy.yml -f docker-compose.intel.yml \
  build llama-xmx
```

## GPU/NPU Monitoring

```bash
# Intel GPU monitor (port 9090)
open http://localhost:9090

# rocm-smi for AMD GPU (RX 7900 XT)
watch -n1 'rocm-smi --showuse --showmemuse 2>/dev/null | grep -E "GPU|VRAM"'

# Intel GPU stats
intel_gpu_top
```

## Build llama.cpp with XMX Support

```bash
cd ~/Projects/personal/lario-llms/llama-cpp
docker build -f Dockerfile.intel-xmx -t llama.cpp:intel-xmx .
```

## Performance Tuning

### Memory
- Populate all 4 memory slots (4-channel DDR5-7200+ Gear 2)
- Enable XMP/EXPO
- Set `PYTORCH_XPU_MEMORY_FRACTION=0.85` for IPEX

### CPU
- Governor: performance
- C-states: C1E off for latency-sensitive workloads
- OMP_NUM_THREADS=24 (match 24 cores on 285K)

### GPU/NPU
- NPU: Enable in BIOS, `OPENVINO_DEVICE=NPU`
- GPU XMX: `GGML_INTEL_XMX=ON`, `-DGGML_OPENCL=ON`, `-DGGML_SYCL=ON`
- Power: PL1=PL2=250W+, aggressive fan curve

## Troubleshooting

### NPU not detected
```bash
# Check NPU device
ls -la /dev/accel/
# Should show accel0

# Check level-zero
ls /usr/lib/x86_64-linux-gnu/libze_intel_gpu.so
```

### GPU XMX not working
```bash
# Check OpenCL
clinfo | grep -i intel

# Check Level Zero
ls /usr/lib/x86_64-linux-gnu/libze_intel_gpu.so
```

### Build fails
```bash
# Clean build
docker compose -f docker-compose.yml -f docker-compose.bigcachy.yml -f docker-compose.intel.yml build --no-cache llama-xmx
```

## Network

All services join `lario-net` (external bridge). Internal DNS:
- `ipex-server:8081`
- `openvino-genai:8082`
- `llama-xmx:8080` (via llama-swap on port 8080, exposed as 8083)
- `intel-gpu-monitor:9090`

Host access via localhost ports:
- 8081: IPEX
- 8082: OpenVINO GenAI
- 8083: llama-xmx (via llama-swap)
- 9090: Intel GPU Monitor
