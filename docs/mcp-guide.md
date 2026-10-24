# MCP guide

OpenCode uses fixed model profiles. Select a hardware-prefixed entry directly;
the owner loads it only when idle and refuses conflicts. There is no mutable
alias-switch workflow in the model MCP.

## Read-only model tools

| Tool | Arguments | Result |
| --- | --- | --- |
| `model_status` | `{}` or `{"hardware":"7900xt"}` | Actual resident fixed profile, context, slots, capacity and serving state |
| `model_options` | `{"hardware":"geekom"}` or `{"hardware":"arcB70"}` | Fixed IDs, compact names, context/KV/slots; B70 distinguishes enabled and unvalidated options |

`lario_models` exposes only these two tools on every client. `model_switch`,
`model_start` and `model_stop` are retired from the agent-facing MCP, even if an
old private environment still says `LARIO_MODELS_ALLOW_SWITCH=1`.
Operator controls are at **https://models.in.drlario.org**. See
[model controls and session identity](model-control.md) for On/Off, idle loading,
registered OpenCode run cancellation and its explicit limitations.

Display names begin `Hardware - xxxk y slots - Model`, keeping context and
slot count visible when the rest is truncated. k means 1024 server tokens;
exact limits stay in metadata. This cosmetic change does not change model IDs.

Hardware/provider IDs remain `geekom`, `7900xt`, `rtx5080` and `rtx3060ti`; selectable model
IDs contain their exact immutable configuration. Display names identify the
hardware. The generic legacy IDs are migration pins, not mutable selections.
Client context equals actual server context minus 4096 tokens. The normal
Geekom Smart large capacity profile advertises 241664 client tokens, not 128k.
Geekom Smart/Medium `long-512k` entries each offer 524288 server / 520192
client tokens, three slots and Q8 KV with 2× YaRN. This replaces the two-slot
profiles; both passed short-response/native three-slot checks after the approved
restart. All three live clients have matching entries. Full-window quality remains unvalidated. The default stays
the existing five-slot Smart profile.
Radeon Qwen is 131072 server / 126976 client tokens; RTX Qwen is
65536 server / 61440 client tokens. No retired Radeon 64k/256k entry is added.

## B70 first live profile

B70 is now a separate owner on Bigcachy. The verified first profile is
`b70 - 256k 2 slots - qwen3.8 smrt · KV4`. Its native slots and short response
passed; other B70 profiles remain gated. `model_status({"hardware":"arcB70"})`
reads its actual public budget; `model_options` marks enabled versus unvalidated
options and never loads a model. Select the allowlisted entry in OpenCode.

## Compact names and B70 preparation

Model names use `gkm`, `rdn xt`, `gfc rtx`, `gfc ti`, `intel`, `b70`, with `qwen`, `smrt`
and `md`. Provider arguments remain the stable IDs: geekom, 7900xt, rtx5080,
arcB70 and rtx3060ti. Example display: `b70 - 1696k 2 slots - Muse Glimmer DFlash · KV4 …`.

Ask the agent: **Call lario_models model_options with hardware arcB70 and list
its prepared model names, context, slots and cache location. Do not activate it.**

B70 offers thirteen Q4-family weight/Q4-KV profiles, including Muse DFlash
256k/twelve slots, 512k/six and 1696k/two. The draft cache is Q4 too. These are
calculated memory budgets; Muse's native context is 128k and all three extensions
need quality checks. `model_options` marks each enabled choice; static inventory carries no ready
fleet capacity. `model_status` now also probes the separate Arc owner. No management key or
inference request is needed for discovery. See [B70 calculations](arcb70-capacity-2026-10-23.md).

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

## RTX 3060 Ti vision backend

The RTX 3060 Ti eGPU on mini-mobile has two measured, fixed Qwen3-VL-8B
profiles: `describe` (32k, one slot, up to 2048 image tokens) and `ocr` (32k,
one slot, up to 8192 image tokens). Its backend listens only on mini-mobile's
127.0.0.1:11448 and requires a private backend credential. It is not a fleet
client endpoint; do not point remote OpenCode clients there or expose the key.
The admission gateway and per-client OpenCode credentials are not yet
registered, so profiles can be discovered through `model_options` but are not
yet selectable in OpenCode. `model_status` reports unavailable until the public
gateway is deployed.

Use the RTX 3060 Ti for local design and image review on mini-mobile, while
keeping the coding conversation on its normal text model. The fleet
`lario_images.image_describe` tool still routes to the RTX 5080; automatic
fallback between GPUs is not yet implemented. See
[RTX 3060 Ti details](../rtx3060ti/README.md) for measured performance and eGPU
safety rules.

## Describe, read or compare existing images

`lario_images.image_describe` lets your Geekom/Radeon coding agent inspect
images without changing the session's coding model or reading API keys. It
currently uses the RTX 5080 vision profiles; the RTX 3060 Ti is not part of this
tool's routing chain.
MCP version 1.2.0 is enabled on bigcachy, l-dev-ai and mini-mobile.

```json
{"images":["/absolute/path/screenshot.png"],"prompt":"Describe this screen and identify layout problems.","mode":"describe"}
```

Use `mode: "describe"` (the default) for the fixed RTX 5080 image-description model.
Use `mode: "ocr"` for the fixed OCR/picture-comparison model, optionally supplying
two image paths and asking what changed. The tool resolves immutable profile IDs
from the authenticated owner catalogue and sends images with the private client
key. It never returns that key or asks you to paste it into the conversation.

Paths refer to the machine running OpenCode/MCP. Supply one to four PNG, JPEG
or WebP files, at most 20 MiB combined. `prompt` is optional; `max_tokens` defaults
to 2048 and is capped at 8192. The result includes the actual model ID and text.
This performs vision inference; it does not generate a new image. An idle RTX 5080
loads the selected fixed profile; busy/Off/paused/disabled serving refuses.
Do not force a swap or bypass the gateway if refused.

Instructions to give a coding agent:

> Use the lario_images MCP tool image_describe to inspect /absolute/path/image.png.
> Use mode describe for a visual description, or mode ocr for text extraction and
> picture comparison. Send my question as prompt and use the returned description
> in your work. Do not probe vision:8080, call unauthenticated HTTP endpoints, or
> ask me for API keys. If the RTX is busy or Off, report that and wait.

`vision:8080` is Docker-only compatibility DNS, not a host-side OpenCode address.
The host gateway at :11435 requires authentication; an unauthenticated probe's
credential_required result is expected. The tool handles authentication privately.

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
