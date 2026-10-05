# Intel workloads — native OpenVINO GenAI on bigcachy

Inspected hardware: Core Ultra 9 285K, 24 cores/threads, about 125 GiB usable system RAM,
AVX2 + AVX-VNNI (not AVX512), Arrow Lake Intel iGPU (PCI 00:02.0, renderD129 at inspection),
and Intel AI Boost NPU (8086:ad1d, architecture 3720, `/dev/accel/accel0`). Render-node
numbers can change; use PCI identity. Runtime enumerates CPU, GPU.0 (Intel iGPU), GPU.1
(NVIDIA), and NPU; Intel workloads explicitly use CPU/GPU.0/NPU.

Native Python is required to use the installed host GPU/NPU stack. Avoid the old IPEX,
XMX llama.cpp and unfinished container prototypes in the historical material. System RAM
backs the iGPU and NPU as well as CPU workloads. There is no Intel model-selector alias.

## Exact tested software

- Python 3.12 venv: `/mnt/xfs/AI_Models/openvino/venv`.
- `openvino==2026.4.0`, `openvino-genai==2026.4.0.0`,
  `openvino-tokenizers==2026.4.0.0`; matching ABI is required. Full API dependency pins
  are in [requirements.txt](requirements.txt).
- Intel GPU compute runtime 26.35.39758.10 and Level Zero loader 1.32.0.
- Intel NPU driver 1.38.0 + `intel-npu-compiler` 2026.38-1.1, installed on the host.
  Detection alone was insufficient without the compiler. A tiny graph and full Whisper
  inference now pass without a temporary LD_LIBRARY_PATH override.
- Host `ffmpeg` decodes uploads to mono 16 kHz float audio; `espeak-ng` supplies Kokoro's
  phonemization/fallback, and python-soundfile writes real WAV output.

Software sources: [GenAI 2026.4 release](https://github.com/openvinotoolkit/openvino.genai/releases/tag/2026.4.0.0),
[Intel NPU driver 1.38](https://github.com/intel/linux-npu-driver/releases/tag/v1.38.0),
[GPU runtime](https://github.com/intel/compute-runtime),
[NPU inference support](https://docs.openvino.ai/2026/openvino-workflow-generative/inference-with-genai/inference-with-genai-on-npu.html).

## Fixed resident services

| Service | Model | Device selected | Port / API |
|---|---|---|---|
| embedding | BAAI/bge-m3, local FP16 OpenVINO export | CPU | 8001 `/embed` |
| asr | Whisper large-v3-turbo FP16 OpenVINO export | NPU | 8002 `/transcribe` |
| translation | Qwen3-8B official INT4 OpenVINO export | GPU.0 | 8003 `/translate` |
| tts | Kokoro-82M official INT8 OpenVINO export | CPU | 8004 `/synthesize`, `/voices` |

Configuration: [runtime.env](runtime.env), instantiated `lario-intel@<service>.service` user
units. `./intel/install.sh` installs/enables them; native model exports and the venv must exist
first. [download_models.py](scripts/download_models.py) downloads the three official exports;
[prepare_models.py](scripts/prepare_models.py) converts the original BGE-M3 checkpoint using
Optimum Intel in a separate export environment. Weights and caches belong on XFS.
All services expose `/health`; inference is the verification, not health alone.

## Client tools

[tools/intel_tools.py](tools/intel_tools.py) provides seven MCP tools and a CLI:
health, translation, transcription, speech synthesis, voice discovery, embeddings
and semantic ranking. Audio input and WAV output paths refer to the client machine
or agent container. Existing output files cannot be overwritten. Embedding responses
omit raw vectors by default; ranking returns document indices and scores.

```sh
python3 intel/tools/intel_tools.py --call intel_health --args '{}'
python3 intel/tools/intel_tools.py --call intel_translate \
  --args '{"text":"Do not delete the 24 retained files.","target_lang":"Portuguese"}'
```

Set `LARIO_INTEL_HOST` to bigcachy's reachable address on remote clients. Without
`--call`, the program serves MCP over stdio. Tool discovery does not connect to
bigcachy, so starting a client before the model host does not lose the tools;
subsequent calls reconnect normally. machine-setup vendors this client and renders
OpenCode and Cline MCP settings. Hermes deploy installs it as an individual boot
artifact from the canonical source; parked agents receive it on their next deploy.
The installed Hermes MCP SDK successfully discovered seven tools and translated
text through the container-to-host route.

Intel Qwen is retained solely as the fixed translation model. Its experimental
coding provider and chat API were removed at the user's request after an unreliable
OpenCode coding test. Choose Geekom/Radeon/RTX for chat and use Intel through the tools.
Translation serializes pipeline/tokenizer operations and bounds generation to 120
seconds after generation callbacks begin; cold prefill is not preemptible by that
callback. Matching pipeline generation defaults are loaded afresh per request.

## Embedding compatibility

The existing RAG space is fixed: `BAAI/bge-m3`, 1024 dimensions, CLS pooling, L2 normalization,
no query prefix, 8192-token input. The FP16 export preserves this contract, and `/embed`
rejects other model identities or disabled normalization. CPU and iGPU vectors were compared
with the original Transformers encoder: minimum cosine on four multilingual test texts was
0.9999999992 (CPU) and 0.99999179 (GPU); pairwise ranking was preserved. This is a smoke
compatibility check, not a complete corpus-retrieval evaluation. Changing dimensions alone
would not preserve vector compatibility. [Model card](https://huggingface.co/BAAI/bge-m3).

NPU embedding compiled only with static padding/batch one and a 512-token test configuration.
That shorter window changes the RAG input contract, so it is not selected. CPU retains the full
window and frees both discrete GPUs. Both RAG `/ingest` and KB ingest supply explicit BGE-M3
vectors; `/retrieve` embeds queries in the same space.

Chroma mounts its persistent store at `/data`. Inspection before migration found only the empty
`default` collection in the live server; old KB collections were not present there. A stopped
copy of the actual `/data` was retained, and source KBs must be ingested into the corrected
persistent server. This discovery is distinct from preserving embedding compatibility.

## Measurements and limits

Measured inference times, one small workload per device/process; compile times are separate.
Exact results and initial failures are in [research](research/).

| Workload | CPU | Intel iGPU | NPU |
|---|---:|---:|---:|
| BGE-M3, four short texts | 0.229 s | 0.213 s | 0.748 s (512-token config) |
| Whisper, 10.435 s English clip | 3.220 s | 2.570 s | 2.019 s |
| Qwen translation, one sentence, thinking disabled | 5.305 s | 1.399 s | export fails compilation |
| Kokoro, 1.925 s English speech | 0.927 s | 8.025 s | 1.021 s |

NPU Whisper cold compilation took 73.9 seconds; Kokoro NPU took 50.8 seconds and emitted
compiler diagnostics despite generating a valid waveform. CPU is the simpler and faster Kokoro
choice here. The Qwen export's grouped/asymmetric quantization failed NPU compilation; NPU
LLM exports require the constraints documented by Intel, including symmetric INT4 and
channel-wise quantization for >4B models. Its working CPU/iGPU export is retained.

These measurements justify the device split for these tested exports. They do not establish
best translation quality across all languages or a benchmark ranking for ASR. Translation tests
preserved meaning, negation and numbers in Portuguese; English synthesized speech was accurately
transcribed by NPU Whisper. Broader quality evaluation remains useful before changing models.
Whisper turbo is for transcription; text translation is the separate Qwen service.

Kokoro uses the model's expected 510×1×256 speaker tensor, a supported voice and language,
and produces 24 kHz WAV audio. espeak-ng enables non-English phonemization and English fallback.
Japanese/Chinese end-to-end synthesis is not advertised in this service. [Official sample](https://openvinotoolkit.github.io/openvino.genai/docs/samples/cpp/speech_generation/).

OpenVINO Model Server 2026.4 also provides native GenAI audio APIs, but is not layered over this
small Python service stack: it would duplicate serving without improving the measured device
placement. The old placeholders have been replaced by tested GenAI pipelines.
