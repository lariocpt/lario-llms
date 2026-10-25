# MCP guide

OpenCode uses fixed model profiles. Select a hardware-prefixed entry directly;
the owner loads it only when idle and refuses conflicts. There is no mutable
alias-switch workflow in the model MCP.

## Read-only model tools

| Tool | Arguments | Result |
| --- | --- | --- |
| `model_status` | `{}` or `{"hardware":"geekom7900xt"}` | Actual resident fixed profile, context, slots, capacity and serving state |
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

Hardware/provider IDs remain `geekom`, `geekom7900xt` and `rtx5080`; selectable model
IDs contain their exact immutable configuration. Display names identify the
hardware. The generic legacy IDs are migration pins, not mutable selections.
Client context equals actual server context minus 4096 tokens. The normal
Geekom Smart large capacity profile advertises 241664 client tokens, not 128k.
Geekom Smart/Medium `long-512k` entries each offer 524288 server / 520192
client tokens and Q4 KV with 2× YaRN. Regular Smart/Medium share Q4 weights and
a context pool sized from memory headroom, with a ceiling of ten stream slots
and 1572864 pooled tokens. All three clients have matching entries. Full-window
quality remains unvalidated. The default stays the Smart 245760-token profile.
Radeon Qwen is 131072 server / 126976 client tokens; RTX Qwen is
65536 server / 61440 client tokens. No retired Radeon 64k/256k entry is added.

## B70 enabled profiles

B70 is now a separate owner on Bigcachy. The verified first profile is
`b70 - 256k 2 slots - qwen3.8 smrt · KV4`. Its native slots and short response
passed; Smart/Medium 128k, 256k and 512k are now allowlisted, with seven other
profiles still gated. `model_status({"hardware":"arcB70"})`
reads its actual public budget; `model_options` marks enabled versus unvalidated
options and never loads a model. Select the allowlisted entry in OpenCode.

## Compact names and B70 preparation

Model names use `gkm`, `rdn xt`, `gfc rtx`, `gfc ti`, `intel`, `b70`, with `qwen`, `smrt`
and `md`. Provider arguments remain the stable IDs: geekom, geekom7900xt, rtx5080,
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
The public admission gateway and scoped client credentials are installed. The
images MCP prefers this card for one or two images totalling at most 6 MiB,
and falls back to the RTX 5080 when unavailable/busy/Off or above those limits.
The overall input ceiling is four PNG/JPEG/WebP files and 20 MiB. These are
compressed-input routing limits; they do not guarantee legibility of tiny text
in a long screenshot. Use tiles and OCR where appropriate. Generation is always
on the RTX 5080; the TI vision model does not generate images.

## Shared frontend and brand workflow — MCP 1.3.0

The canonical tools live in machine-setup/shared/agents/image_tools.py. The old
lario-llms image_tools.py is a compatibility entrypoint, not a second implementation.

| Tool | Purpose |
| --- | --- |
| image_screenshots | Start a durable URL/URL-array capture job at responsive widths |
| image_design_analysis | Start sequential, paired screenshot reviews and a brand/frontend report |
| image_job_status | Read progress, manifest and report paths without repeating work |
| image_job_cancel | Cancel the exact local worker and keep completed artifacts |
| image_contrast | Calculate opaque hex foreground/background WCAG contrast |
| image_describe | One immediate description/OCR/comparison request |
| image_generate | Generate on the idle RTX 5080 and restore its prior chat state |

Example capture:

```json
{"urls":["http://localhost:4321/","http://localhost:4321/gallery/"],"widths":[400,479,480,767,768,1440]}
```

Poll the returned job_id with image_job_status. JPEGs and JSON metadata persist
under ~/.local/share/lario-images/jobs (or XDG_DATA_HOME). Captures use a fresh
sandboxed Chromium with software rendering and no inference GPU. Local Chromium
and the pinned browser runtime are required; machine-setup's user provisioning
installs the runtime when Chromium exists. Headless Geekom has no local Chromium;
run captures on mini-mobile/Bigcachy or explicitly install that system dependency.
No browser dependency or model download happens during a tool call.

Each job permits up to 32 URLs, 16 widths and 256 combinations. Defaults cover
400,480,600,768,980,1200,1440,1920. Supply actual CSS boundaries for the project.
Pages resize between widths; reload_each_width:true tests load-specific layouts.
Waits are bounded; failures, inaccessible stylesheets and incomplete embeds are
not silently called successful audits. Long pages use bounded image tiles; the
manifest records truncation if even those limits cannot cover the page.

Pass a curated image list to image_design_analysis. Consecutive pairs are
compared sequentially on the TI-first/5080-fallback route. The report separates
visual evidence from proposals and records the actual hardware/model. Raw vision
findings need editorial review; they cannot verify keyboard behaviour, hidden
states, font installation or contrast. image_contrast measures opaque #RRGGBB
pairs separately; whole-page accessibility still requires real testing.

## OpenCode image attachments

The installed prompt hook accepts PNG/JPEG/WebP local-file and inline image
attachments. It privately calls the same vision route, then passes labelled
textual evidence to the coding model. It does not send image pixels to a
text-only Radeon/Geekom model. Missing vision evidence fails the prompt rather
than silently dropping an attachment. Non-image files remain attached.

Identical image bytes and question reuse a private evidence cache. Keys and
base64 image data never enter model-control logs or tool results. Remote image
URLs are not fetched by the attachment bridge; attach a local file. Client
configuration advertises mediated attachment support; this is not native vision
capability in the text-model hardware registry. Reload OpenCode after deployment.

## Describe, read or compare existing images

```json
{"images":["/absolute/path/screenshot.png"],"prompt":"Review the visible layout.","mode":"describe"}
```

mode describe selects the fixed description profile; mode ocr selects the OCR
profile. The tool resolves immutable IDs and authenticates privately. A request
may load a profile only through normal admission; it never forces a busy model
swap. Backend requests are bounded at 180 seconds. Results identify the actual
hardware/model and any fallback; an unavailable fleet returns an explicit error.

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
