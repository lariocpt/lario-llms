# Geekom 512k, two-slot Qwen3.8 profiles — October 22, 2026

Two additional fixed profiles use the installed dense Qwen3.8-27B weights on
l-dev-ai: Smart Q8_K_XL and Medium Q4_K_XL. Each provides two 524288-token slots,
Q8 K/V and two coding reservations (zero advisory fleet slots). The long-512k
preset applies only to these two base models, not Flash or the 128k entries.
Existing fixed IDs, defaults, weights and context geometries remain unchanged.

## Context extension and client metadata

The [official Qwen3.8-27B model card](https://huggingface.co/Qwen/Qwen3.8-27B)
states 262144 native tokens and extension through YaRN. These profiles explicitly
set `--rope-scaling yarn --rope-scale 2 --yarn-orig-ctx 262144`. The installed
l-dev-ai llama-server help confirms all three flags. This is a context extension,
not native 512k training or a measured long-context quality guarantee.

Backend pooled context is `-c 1048576 --parallel 2`: **524288 per slot**, not
1048576 per request. OpenCode advertises **520192 client tokens** after the
standard 4096-token serving margin, with the existing 8192 output cap. Immutable
IDs include the context, Q8 KV, two slots and YaRN arguments. They use the normal
idle-only activation, capacity and Off/pause controls.

## Conservative memory calculation

Using the installed GGUF header geometry documented in the
[Q8 budget](geekom-q8-slot-budget-2026-10-17.md), estimate 17 full-attention layers,
four KV heads and 256 key/value dimensions. Q8_0 uses 34/32 bytes per value:

`524288 × 17 × 4 × (256+256) × 34/32 = 18.0625 GiB per slot`.

Two slots estimate **36.125 GiB** of attention cache, versus **42.33398 GiB**
for the existing five × 245760 profile. Weight-file proxy plus cache is about
**65.42 GiB Smart** or **52.48 GiB Medium**. This excludes recurrent state,
compute/staging buffers, allocator overhead and other processes. The historical
GTT budget is approximately 105 GiB; this is an allocation estimate, not live
free memory or measured peak use. Profiles remain provisional until validated.

## Deployment boundary

Adding profiles changes the static backend and admission catalogues. Source
checks can run without loading weights. Do not restart a busy Geekom backend or
advertise undeployed profiles in live OpenCode. Reconcile the backend and gateway
in a controlled idle window or after explicit approval to disconnect requests;
then install the matching OpenCode catalogues on all three clients. No full-window
prefill, recall, quality or performance benchmark is claimed by these configs.

## Deployed and short-request verified

The user approved restarting Geekom despite five active requests. Admission was
paused, backend/gateway restarted with the new catalogue, then both 512k profiles
answered a short request with `OK`. Each native slot endpoint reported exactly
`[524288, 524288]`, with two idle slots after completion. Q8 KV and explicit
YaRN flags remain in the registered backend commands.

The previous Smart 245760-token/five-slot profile was restored and admission
resumed. Matching client profiles were installed using machine-setup's renderer
and supported OpenCode reload on bigcachy, l-dev-ai and mini-mobile. No existing
conversation was migrated to a different model. These are allocation/geometry
and short-response checks, not full-window quality or performance measurements.

## Three-slot memory estimates and short labels

These estimates concern the installed Qwen3.8-27B Smart/Medium weights; a
separate Qwen3.5 checkpoint needs its exact size and quantization identified.
A maximum usable three-slot window has not been measured. The existing live
validation was two slots, not three. No new three-slot profile is implied here.

| Context per slot | Three-slot Q8 attention cache | Smart Q8 weight + cache | Smart remainder in 105 GiB | Medium Q4 weight + cache | Medium remainder |
| --- | ---: | ---: | ---: | ---: | ---: |
| 512k | 54.19 GiB | 83.49 GiB | 21.51 GiB | 70.54 GiB | 34.46 GiB |
| 600k | 63.50 GiB | 92.80 GiB | 12.20 GiB | 79.85 GiB | 25.15 GiB |
| 640k | 67.73 GiB | 97.03 GiB | 7.97 GiB | 84.09 GiB | 20.91 GiB |
| 768k | 81.28 GiB | 110.58 GiB | Does not fit | 97.63 GiB | 7.37 GiB |

Remainders must still cover recurrent state, compute buffers and other GPU
consumers. 512k Smart or 640k Medium are conservative candidates for later
three-slot validation; larger rows are tight arithmetic candidates, not tested
recommendations. Fitting memory does not establish interactive latency. The
current five-slot Smart workload exposed severe long-prefill/decode interference,
so concurrency needs realistic validation before any maximum is claimed.

Model display labels now begin `Hardware - xxxk y slots - Model …`. Here k means
1024 server tokens: 245760 displays as 240k, 122880 as 120k, and 524288 as 512k.
Exact client limits remain in metadata, and immutable IDs/context/slot geometry
do not change. The operator frontend can reformat old owner labels without
restarting an inference gateway.
