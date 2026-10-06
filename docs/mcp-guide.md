# MCP guide

Three local MCP servers connect OpenCode to the fleet: `lario_intel` for fixed
Intel workloads, `lario_models` for actual model status and selection, and
`lario_images` for the RTX diffusion models. They use stdio JSON-RPC; they do not
load model weights in the client.

## What each client can do

| Client | Intel tools | Model tools | Image tools |
| --- | --- | --- | --- |
| bigcachy | All seven | Status, options and guarded switching | Options and generation |
| l-dev-ai | All seven | Status, options and guarded switching | Options and generation over existing owner SSH |
| cachyos-mini-mobile | All seven | Status and options | Options only |
| media | All seven | Status and options | Options only |
| Parked Linux Hermes agent, on its next deploy | All seven | Status and options | Options only |

Owner actions rely on existing SSH/controller access. Consumer model keys grant
inference access, not administration. No backend or management keys are distributed
to Mini/mobile/media, and media's Git synchronization opt-out is retained. Every
Hermes agent is currently paused; source changes do not resume the fleet.

## Show the active alias models

Ask OpenCode: “Use model_status to show the active models, contexts and slot counts
for Geekom, Radeon and RTX. Distinguish saved selection from actual residency.”

| Tool | Arguments | Result |
| --- | --- | --- |
| `model_status` | `{}` or `{"hardware":"7900xt"}` | Ready/unavailable state, actual resident model, per-slot context and slots; owner mode also supplies saved target, occupancy and a fresh switch token |
| `model_options` | `{"hardware":"rtx5080"}` | Exact enabled `model@preset` choices, context, KV placement, reservations and validation labels |
| `model_switch` | Hardware, exact option, fresh switch token; experimental choices require `allow_experimental:true` | Guarded owner switch with existing rollback; available only on owner-capable clients |

Hardware names are exactly `geekom`, `7900xt` and `rtx5080`. A picker name in
OpenCode is static and does not automatically change with the selected weights.
Read-only consumer fallback reports actual residency but cannot verify the saved
alias target or occupancy on the legacy endpoint; unknown is not idle.

## Switch a model from OpenCode

1. Call `model_options` for the desired hardware.
2. Call `model_status` for a fresh owner state and `switch_token`.
3. Explicitly request the exact option with that token. If its current metadata
   says experimental, explicitly allow the controlled choice.
4. Check `model_status` again after the switch completes.

Example request after obtaining a fresh token:

```json
{"hardware":"7900xt","option":"qwen3.8@fast-128k","switch_token":"<fresh 64-character token>","allow_experimental":true}
```

Example prompt: “List Radeon choices, then switch to the 128k Qwen option only if
the card is idle and healthy. Report the resulting resident context.”

Held, active, unknown, unhealthy or stale hardware is refused. There is no force
switch, sudo, download or OpenCode restart. Do not reuse old tokens, guess a
number from another host's menu, or request a concrete model while unrelated work
is active: the legacy chat proxy can otherwise change residency.

The same owner menus are available in a terminal:

```sh
7900xt options
7900xt qwen3.8@fast-128k --experimental
rtx5080 qwen3.8@fast-64k --experimental
geekom qwen38-flash@flash-128k --experimental
```

Use `--experimental` only while the option is labelled that way; promoted options
work without it. Radeon Qwen offers 64k and 128k; RTX Qwen offers only 64k. The
removed 32k/256k choices have not removed shared, still-used model weights.

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

## Configuration, credentials and synchronization

Canonical clients are in lario-llms `intel/tools`, `shared/model_tools` and
`rtx5080/image-generation`. machine-setup vendors them in `shared/agents` and
renders `machines/<machine>/config/opencode.jsonc` over its shared base.
Edit those sources and use the renderer; preserve unrelated providers and private
credentials. Files/backups with private keys use mode 0600. Git stores dummy keys.

OpenCode v2 requires the complete MCP definition and explicit Code Mode exposure.
Configured long execution timeouts allow a guarded warmup/image operation; they
do not imply that an unresponsive owner is ready. The model selectors do not
restart OpenCode. New configuration normally applies on its next start; an idle
running v2 client can use its supported complete-definition reload API.

`opencode mcp list` checks connections. An actual successful tool invocation is
needed to prove execution; discovery is available even when a model host is off.
MCP tool clients reconnect on later calls, regardless of which inference host
boots first. The remaining physical power-order tests are separate.

## Troubleshooting

| Symptom | Check / action |
| --- | --- |
| Model picker still says an old name | Use model_status; picker names are static. Render canonical sources and retire old default-agent overrides as well as the global model |
| Tool missing on Mini/mobile/media | Switching and generation are deliberately absent there; verify the seven Intel tools and read-only model/image tools |
| Connected MCP but failed tool call | Run the actual tool; inspect host reachability, owner occupancy and complete Code Mode configuration |
| Switch refused | Finish/cancel active requests through their client, remove only an authorized hold, then obtain fresh status; never force a busy owner |
| Oversized prompt | Check actual per-slot context and private consumer limits; smaller context does not add model weights |
| Image path not visible locally | The PNG is on bigcachy; retrieve that specific artifact through existing access |
| Host is offline | Tool discovery still works; retry after the owner and its services return |
| NVIDIA is hot or unavailable | Stop the owned benchmark load, read temperatures/fans/throttling and investigate cooling before heavier tests |

The production admission gateway is still inactive. Current reservation budgets
are advisory; consumer keys on legacy ports do not prove enforcement or prevent
backend bypass. Read the dated benchmark report for stable/experimental decisions
and the original failures that remain part of the evidence.
