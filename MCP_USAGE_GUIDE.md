# MCP usage guide — commands

Every MCP tool below can be used two ways:

- **In OpenCode:** ask for the tool by name, e.g. "use `model_status` for geekom".
  Code Mode exposes the same tools as `tools.<server>.<tool>({...})`.
- **In a terminal:** the model and Intel clients are also CLIs —
  `python3 <client> --call <tool> --args '<json>'`. Run from
  `~/Projects/personal/lario-llms`. The image client is stdio-only; use the
  `rtx5080 images ...` controller commands shown below.

Check connections with `opencode mcp list`. A successful tool call, not discovery,
proves the host is live.

Clients:

| Server | Client file |
| --- | --- |
| `lario_models` | `shared/model_tools/model_tools.py` |
| `lario_intel` | `intel/tools/intel_tools.py` |
| `lario_images` | `rtx5080/image-generation/image_tools.py` |
| `lario_media` | `media/tools/media_tools.py` (see the pending section) |

---

## Models — `lario_models`

Hardware names are exactly `geekom`, `7900xt`, `rtx5080`.

| Command | Args | Result |
| --- | --- | --- |
| `model_status` | `{}` or `{"hardware":"geekom"}` | Resident model, per-slot context, slots; owner mode adds saved alias target, occupancy and a fresh `switch_token` |
| `model_options` | `{"hardware":"rtx5080"}` | Numbered `model@preset` choices with context/slots/reservations |
| `model_switch` | `{"hardware":...,"option":...,"switch_token":...}` (+ `"allow_experimental":true` when labelled experimental) | Guarded owner switch with rollback |

```sh
python3 shared/model_tools/model_tools.py --call model_status  --args '{}'
python3 shared/model_tools/model_tools.py --call model_options --args '{"hardware":"geekom"}'
LARIO_MODELS_ALLOW_SWITCH=1 python3 shared/model_tools/model_tools.py --call model_status --args '{"hardware":"geekom"}'   # adds occupancy + switch_token
LARIO_MODELS_ALLOW_SWITCH=1 python3 shared/model_tools/model_tools.py --call model_switch  --args '{"hardware":"geekom","option":"qwen38-flash@flash-128k","switch_token":"<fresh token from model_status>","allow_experimental":true}'
```

Switch sequence: `model_options` → `model_status` (fresh token) → `model_switch` →
`model_status` again. Tokens are single-use; held, active, unknown or unhealthy
hardware is refused and there is no force switch.

Owner mode (status with alias target, occupancy, `switch_token`, plus
`model_switch`) needs `LARIO_MODELS_ALLOW_SWITCH=1` — set on bigcachy and
l-dev-ai by their OpenCode config. Prefix the terminal commands with it, or
status falls back to the read-only public view. Mini/mobile/media are
status/options only.

Same switches without the MCP. `7900xt` and `rtx5080` are on PATH on bigcachy;
`geekom` is `geekom/geekom` in this repo and must switch on its host, l-dev-ai.

```sh
./geekom/geekom                     # interactive menu (needs a terminal)
./geekom/geekom options             # numbered choices
./geekom/geekom list                # models, slots, context, reserved
./geekom/geekom status              # saved selection + live /running
./geekom/geekom budget              # live slots/context as JSON
./geekom/geekom qwen38-flash@flash-128k --experimental
7900xt qwen3.8@fast-128k
rtx5080 qwen3.8@fast-64k
```

---

## Intel — `lario_intel`

Services are resident on bigcachy (`embedding` 8001, `asr` 8002, `translation`
8003, `tts` 8004). `audio_path` and `output_path` are on the machine running the
MCP, not on bigcachy.

| Command | Args | Result |
| --- | --- | --- |
| `intel_health` | `{}` | State of the four services and their devices |
| `intel_translate` | `{"text":...,"target_lang":...,"source_lang":"English"}` | Translation via iGPU Qwen3-8B INT4 |
| `intel_transcribe` | `{"audio_path":"/tmp/meeting.wav","language":"en"}` | Original-language text (NPU Whisper, ≤50 MB) |
| `intel_synthesize` | `{"text":...,"output_path":"/tmp/hello.wav","voice":"af_heart","speed":1.0}` | New Kokoro WAV; never overwrites |
| `intel_voices` | `{}` | Kokoro voice IDs and languages |
| `intel_embed` | `{"texts":[...],"return_vectors":false}` | BGE-M3 1024-d normalized embeddings (metadata/norms by default) |
| `intel_rank` | `{"query":...,"documents":[...],"top_k":5}` | Indices, scores and texts by cosine similarity |

```sh
python3 intel/tools/intel_tools.py --call intel_health     --args '{}'
python3 intel/tools/intel_tools.py --call intel_voices     --args '{}'
python3 intel/tools/intel_tools.py --call intel_translate  --args '{"text":"Where is the station?","source_lang":"English","target_lang":"Portuguese"}'
python3 intel/tools/intel_tools.py --call intel_transcribe --args '{"audio_path":"/tmp/meeting.wav"}'
python3 intel/tools/intel_tools.py --call intel_synthesize --args '{"text":"Hello there.","output_path":"/tmp/hello.wav","voice":"af_heart","speed":1.0}'
python3 intel/tools/intel_tools.py --call intel_embed      --args '{"texts":["first doc","second doc"],"return_vectors":false}'
python3 intel/tools/intel_tools.py --call intel_rank       --args '{"query":"which doc covers backups?","documents":["first doc","second doc"],"top_k":2}'
```

Voices: `af_heart` English, `pf_dora` Portuguese; use `intel_voices` for the real set.

---

## Images — `lario_images`

Model IDs are `qwen-image` and `flux-klein`. Width/height 256–1024 in multiples
of 64; steps 1–40 (defaults 25 and 4). The PNG lands on bigcachy.

| Command | Args | Result |
| --- | --- | --- |
| `image_options` | `{}` | Configured models; owner clients also verify installation |
| `image_generate` | `{"model":...,"prompt":...,"width":512,"height":512,"steps":4,"seed":17}` | One PNG path, then the saved chat profile is restored |

`image_tools.py` is stdio-only (no `--call`). From a terminal use the owner
controller instead (bigcachy):

```sh
rtx5080 images options
rtx5080 images generate --model flux-klein --prompt "A clean mountain icon, blue on white" --width 512 --height 512 --steps 4 --seed 17
```

`image_generate` is only exposed where `LARIO_IMAGES_ALLOW_GENERATE=1`; other
clients list options only. Generation takes the RTX exclusively and the
chat/vision endpoint is unavailable during the job.

---

## Media — `lario_media` (pending)

The media toolkit (`media/tools/media_tools.py`) is still being finalised on
`fix/retained-gpu-contexts-and-guides-20261006` and is not in `main` yet. Add the
command table here once that branch is merged.
