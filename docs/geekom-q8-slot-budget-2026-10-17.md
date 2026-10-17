# Geekom Qwen Q8 slot budget — 2026-10-17

Calculated configuration, **not a runtime benchmark**. The currently resident
Flash profile is untouched; changed Smart/Medium profiles apply on the next
guarded selection/start. Keep two coding reservations per profile.

| Dense profile | Per-slot tokens | Previous FP16 capacity slots | New Q8 capacity slots | Q8 balanced slots | Capacity advisory fleet slots |
| --- | ---: | ---: | ---: | ---: | ---: |
| Smart / Medium | 245760 | 4 | 5 | 4 | 3 |
| Smart-128k / Medium-128k | 122880 | 8 | 10 | 6 | 8 |

The names "128k" and the larger-context names retain their existing exact token
counts. This change does not implement the deferred OpenCode Geekom alias/context
redesign. All dense capacity choices are experimental until runtime validation;
balanced already carries that label. More slots do not promise more total tokens
per second: all requests still share one GPU and its memory bandwidth.

## Evidence and calculation

Read the headers of both actual GGUF files on l-dev-ai without loading them:

- Architecture: `qwen35`, 65 blocks, full attention interval 4.
- Four KV heads; key and value dimensions each 256.
- Smart weight file: 31457991680 bytes (29.30 GiB).
- Medium weight file: 17559178144 bytes (16.35 GiB).
- Existing measured GTT pool: approximately 105 GiB, from the host inventory.

Use **17 attention layers as a conservative upper estimate** (ceil(65/4)),
including any extra block in the header. This is an estimate of ordinary
attention K/V storage, not all hybrid recurrent state or total process memory.

llama.cpp [defines q8_0](https://github.com/ggml-org/llama.cpp/blob/master/ggml/src/ggml-common.h)
as 32 one-byte values plus a two-byte scale, hence 34/32 bytes per value.
FP16 uses two bytes per value. The attention-cache estimate is:

```text
bytes_per_slot = context × 17 × 4 × (256 + 256) × (34/32)
245760 tokens: 8.4668 GiB per slot
122880 tokens: 4.2334 GiB per slot
```

Both proposed capacity profiles allocate about **42.33 GiB** of attention cache.
The equivalent previous 4/8-slot FP16 estimate is 63.75 GiB. The ratio is
`(5/4) × (34/64) = 0.6640625`: about **33.6% less attention-cache storage**
while offering 25% more slots.

| Weight configuration | File-size proxy + capacity attention cache | Remainder within 105 GiB GTT estimate |
| --- | ---: | ---: |
| Smart Q8 weights | 71.63 GiB | 33.37 GiB |
| Medium Q4 weights | 58.69 GiB | 46.31 GiB |

The remainder must accommodate recurrent state, compute/staging buffers,
alignment, allocator overhead and other GPU consumers. File size is only a
proxy for resident weights; neither table is a measured peak-memory claim.
Balanced allocates an estimated 33.87 GiB for the large contexts and 25.40 GiB
for the smaller contexts. Flash already used Q8 and gains no slots from this change.

## Later validation

During the planned reorganization, validate actual allocations, full-context
quality/retrieval, simultaneous requests, latency and memory pressure before
promoting these profiles or increasing concurrency further. Source/config checks
now enforce explicit Q8 K/V flags, unchanged per-slot context and reservations,
and a smaller cache budget than the previous FP16 capacity.
