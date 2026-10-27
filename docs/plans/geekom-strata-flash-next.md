# Geekom Flash Next with Strata: Q3 capacity plan

Planning only, 2026-10-27. No Geekom model, configuration or service changes.
The RTX OpenCode sidekick reviewed the pinned Strata source. Codex independently
recomputed the arithmetic and checked the extra main-session allocation.

## Verified inputs

- Existing `UD-Q3_K_XL`: three files under `/mnt/AI_Models/gguf/qwen38-flash`,
  totalling **89,986,353,824 bytes = 83.8063 GiB**. Sizes were read on l-dev-ai;
  this was not another full checksum pass.
- Geekom's integrated Radeon is PCI `1002:1586` (gfx1151/Strix Halo).
- Its reported GTT limit is **113,246,208,000 bytes = 105.46875 GiB**.
- Physical RAM is 134,145,425,408 bytes. GTT and CPU memory share that RAM;
  they are never added together in this plan. The discrete 7900 XT is excluded.
- Interpret the user's hard **110 GB** literally as 110,000,000,000 bytes =
  **102.4455 GiB**. If 110 GiB was intended, the current 105.46875 GiB GTT
  limit is the tighter bound. Do not change that limit as part of setup.

## Persistent session state

Use T=262,144 or 131,072 tokens. The model has 12 full-attention layers and
36 recurrent layers. Strata's q4_0 cache uses Hadamard rotation; it is not
numerically identical to ordinary llama.cpp Q4 KV.

Q4 K/V bytes/token = 12 layers × 2 KV heads × 2 (K,V) × 256 dimensions × 18/32
= **6,912 bytes/token**. Q8 instead uses **12,672 bytes/token**.

Add pooled indexer state, approximately 1,536 bytes/token; one shared RoPE
table per session, 256 bytes/token; and GDN recurrent state:

`36 × (128 × 48 × 128 + 3 × 10,240) × 4 = 117,669,888 bytes`.

| Component, GiB | 128K | 256K |
|---|---:|---:|
| Q4 K/V | 0.84375 | 1.68750 |
| Pooled indexer | 0.18751 | 0.37501 |
| RoPE | 0.03125 | 0.06250 |
| GDN state | 0.10959 | 0.10959 |
| Persistent state subtotal | **1.1721** | **2.2346** |
| With Q8 K/V instead | **1.8752** | **3.6409** |

Page tables, small tails, alignment and working buffers are additional. Reserve
**6 GiB for runtime/prefill** and **1 GiB provisionally for packing differences
and auxiliary buffers**, all inside the hard budget. These are planning
allowances, not measured HIP allocations. No MTP draft model is included.

## Count the main session as well as the batch slots

The pinned implementation allocates a main session, then N additional slot
sessions. Therefore, for homogeneous contexts:

`M ≈ 83.8063 + 7 + (N + 1) × state_per_session_GiB`.

For this one-GPU plan without grouped MTP, cap N at eight. These are estimated
memory ceilings, not throughput promises or validated launch configurations.

| Effective budget | Q4 KV: 256K slots | Q4 KV: 128K slots | Q8 KV: 256K slots | Q8 KV: 128K slots |
|---|---:|---:|---:|---:|
| **110 GB literal: 102.4455 GiB** | **4** | **8** | **2** | **5** |
| Current GTT ceiling: 105.46875 GiB | **5** | **8** | **3** | **6** |

Examples with Q4 KV:

- Four 256K slots: `83.8063 + 7 + 5 × 2.2346 ≈ 101.98 GiB = 109.50 GB`.
- Eight 128K slots: `83.8063 + 7 + 9 × 1.1721 ≈ 101.36 GiB = 108.83 GB`.
- Four 128K slots: approximately **96.67 GiB**.
- Five 256K slots: approximately **104.21 GiB**, above a literal 110 GB cap.

## Recommended options and implementation gates

Start with alternative **4 × 256K / Q4 KV** and **4 × 128K / Q4 KV** presets.
The 128K preset may later increase to six/eight slots if measured latency is
acceptable. Eight is a memory ceiling, not the recommended initial concurrency.

Keep one model resident. Strata's batch slots inherit the same `max_context`;
offering a 128K client limit inside a 256K engine does not halve that slot's
allocation. A mixed four-slot service (e.g. two 256K clients plus two 128K
clients) should therefore be budgeted like four 256K slots. Separate simultaneous
engines would duplicate weights and are excluded.

Use the official Linux HIP Halo engine and matching gfx1151 tuning table.
Do not transfer Intel-only SYCL flags or assume the B70 batch fault applies to
HIP. Preserve Q3 weights and use Q4 KV; compare Q8 only as an explicit option.

The weight budget assumes expert weights are not duplicated in a complete RAM
arena plus a second GPU cache. Audit the native GGUF mapped/resident-complement
path (`--resident-experts`) and an explicitly bounded expert cache, preferably
without prefill borrowing initially. The complement must exclude GPU-resident
experts. Count PLE, embedding, native projections, pack replacements, retained
checkpoints and all actual cache copies within the same budget. If this cannot
be demonstrated, subtract the measured duplicate bytes and recalculate N.

On a later implementation window: prepare the Q3 pack on XFS; install the
engine on the apps partition; wait for owner/native idleness and unload the
existing Geekom model before Flash loads. Test one slot, then four, including
concurrent retrieval, prefix reuse and cancellation. Measure steady and peak
shared-memory use, then full-context ingestion. Enable the presets and sync
OpenCode only after those checks. No swap or disk spill is counted as capacity.

## Source anchors

Pinned Strata revision: `4b9e05a2a806a3fe24f7b2560d98626c37dade35`.

- `include/strata/kernels/kv_q4.hpp`: 18-byte Q4 blocks and bytes/cell.
- `src/core/layer.cpp:738–791`: KV plans, pooled rows, RoPE and state bytes.
- `src/core/session.cpp:43–74`: recurrence and session buffers.
- `src/program/generate.cpp:5220,5345–5423`: main session, batch cap and additional slots.
- `src/core/expert_source.cpp:163–224`: complement omits GPU-resident experts.
- `src/program/generate.cpp:5714–5735,8138–8242`: mapped/resident expert path.
- `docs/STRIX_HALO.md`: official HIP Halo route, UMA/cache accounting and tuning.

The sidekick's draft arithmetic was not used without correction: notably the
128K subtotal, GB conversion and N-versus-N+1 allocations were independently
recalculated here.
