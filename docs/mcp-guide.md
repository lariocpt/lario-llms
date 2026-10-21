# MCP guide

OpenCode uses fixed model profiles. Select a hardware-prefixed entry directly;
the owner loads it only when idle and refuses conflicts. There is no mutable
alias-switch workflow in the model MCP.

## Read-only model tools

| Tool | Arguments | Result |
| --- | --- | --- |
| `model_status` | `{}` or `{"hardware":"7900xt"}` | Actual resident fixed profile, context, slots, capacity and serving state |
| `model_options` | `{"hardware":"geekom"}` | Immutable IDs, hardware/owner, context, KV precision, slots and reservations |

`lario_models` exposes only these two tools on every client. `model_switch`,
`model_start` and `model_stop` are retired from the agent-facing MCP, even if an
old private environment still says `LARIO_MODELS_ALLOW_SWITCH=1`.
Operator controls are at **https://models.in.drlario.org**. See
[model controls and session identity](model-control.md) for On/Off, idle loading,
registered OpenCode run cancellation and its explicit limitations.

Hardware/provider IDs remain `geekom`, `7900xt` and `rtx5080`; selectable model
IDs contain their exact immutable configuration. Display names identify the
hardware. The generic legacy IDs are migration pins, not mutable selections.
Client context equals actual server context minus 4096 tokens. The normal
Geekom Smart large capacity profile advertises 241664 client tokens, not 128k.
Radeon Qwen is 131072 server / 126976 client tokens; RTX Qwen is
65536 server / 61440 client tokens. No retired Radeon 64k/256k entry is added.

## Clients and authority

Bigcachy, l-dev-ai and mini-mobile receive scoped inference credentials and the
v2 identity plugin through machine-setup. Keys identify installations; headers
identify conversation/run within each installation. Inference keys cannot call
owner management endpoints. Management/backend/SSH control keys stay private.

Hermes and other consumers retain read-only model discovery and their existing
inference-role credentials. The parked fleet remains paused. Image/encoder
mutation permissions remain separate and do not grant model lifecycle access.

## Intel tools

| Tool | Arguments / example | Use |
| --- | --- | --- |
| `intel_health` | `{}` | Check four services and their selected devices |
| `intel_translate` | Text, target language, optional source language | Translate through the Intel iGPU Qwen3-8B pipeline |
| `intel_transcribe` | `audio_path`, optional `language` | Upload a client-local audio file to NPU Whisper and return original-language text |
| `intel_synthesize` | Text, a new client-local `output_path`, optional voice/speed | Write a real Kokoro WAV without overwriting an existing file |
| `intel_voices` | `{}` | Discover supported voice IDs and languages |
| `intel_embed` | `texts`, optional `return_vectors:true` | Compatible BGE-M3 vectors; metadata/norms are returned by default |
| `intel_rank` | Query, documents, optional `top_k` | Rank supplied texts by compatible embedding cosine similarity |

Example prompts:

- “Translate this text into Portuguese using intel_translate; keep its numbers
  and negations intact.”
- “Transcribe `/tmp/meeting.wav` with intel_transcribe.”
- “Use intel_synthesize to save this sentence as a new `/tmp/hello.wav`.”
- “Rank these documents against my question with intel_rank.”

Audio paths refer to the machine running the MCP, including an agent container,
not a path on bigcachy. Speech input is capped at 50 MB. Common voices include
`af_heart` for English and `pf_dora` for Portuguese; use voice discovery for the
actual supported set. Japanese/Chinese end-to-end synthesis is not advertised.
Whisper transcription and Qwen text translation are separate operations.

## Generate an image

| Tool | Arguments | Result |
| --- | --- | --- |
| `image_options` | `{}` | Qwen Image and FLUX Klein choices; owner clients also verify the installation |
| `image_generate` | Model, prompt; optional width, height, seed and steps | One generated PNG path on bigcachy, followed by saved chat-profile restoration |

Model IDs are `qwen-image` and `flux-klein`. Width/height are 256–1024, in multiples
of 64; steps are 1–40. FLUX's tested distilled workflow uses four steps. Example:

```json
{"model":"flux-klein","prompt":"A clean mountain icon, blue on white","width":512,"height":512,"steps":4,"seed":17}
```

The controller needs at least 40 GiB available host RAM and an idle, healthy RTX.
During the job its chat/vision endpoint is unavailable. Text encoders use RAM;
the image worker is started on demand and stopped after the job. The returned
path is on bigcachy, even when requested from l-dev-ai. Only explicitly requested
generation is allowed; discovery alone does not borrow the card.

## Configuration and troubleshooting

Source clients are in lario-llms `intel/tools`, `shared/model_tools`,
`rtx5080/image-generation`, and `rtx5080/encoder`. machine-setup vendors clients
in `shared/agents` and renders its per-machine overlays. Preserve unrelated
providers/plugins and keep all private credentials/backups outside Git at mode
0600. Model catalog schema 2 exports the same fixed IDs as the OpenCode picker.

`opencode mcp list` checks connections; an actual tool call proves execution.
Read-only discovery works when a model host is off. The owner gateway and
operator page reconnect without a required boot order. On starts serving cold;
Off persists until explicitly cleared. Historical benchmark results remain in
[October 6](benchmarks-2026-10-06.md) and [October 17](benchmarks-2026-10-17.md).
This configuration rollout does not add benchmarks or promote provisional slots.

| Symptom | Action |
| --- | --- |
| Different profile busy | Finish or explicitly cancel its active work, then retry the exact fixed entry |
| Hardware/profile disabled | Use operator controls; ordinary agents cannot bypass Off |
| Capacity exhausted | Same-profile slots are full; honor retry backoff |
| Backend state unknown | Check owner/device status; never force a model swap |
| Early compaction | Verify the selected immutable ID and its client context, not an old alias cap |
| Runner interruption unconfirmed | Inference was cancelled; inspect the originating client; do not assume its tools stopped |
| Host offline | Wait for it to return; offline does not mean its processes stopped |
