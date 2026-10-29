# Flash Next extended context modes — 2026-10-30

These are alternative resident modes, not mixed-size shared native slots.
The owner gateway reserves the whole selected window for each request, including
background titles, compaction and agent requests. A request above the native
256K training window uses explicit YaRN extension; full-window answer quality
and sustained long-prompt throughput remain unvalidated.

| Owner | Weights / KV | New mode | Total admission tokens | RoPE extension |
|---|---|---|---:|---|
| Geekom (l-dev-ai) | existing UD-Q3_K_XL / q4_0 | 2 × 524,288 | 1,048,576 | YaRN 2× |
| Arc B70 Pro (bigcachy) | existing UD-Q4_K_XL / q4_0 | 1 × 786,432 | 786,432 | YaRN 3× |

The existing four × 256K Geekom and three × 256K B70 modes remain available
for rollback. The extended and original modes are exclusive: the gateway refuses
requests for a different resident mode until the operator switches modes. This
prevents loading duplicate weights or presenting the original slots as spare
capacity beside the new ones. OpenCode context limits subtract the normal 4096
token margin; output remains 8192 tokens and counts toward the physical window.

## Geekom implementation and evidence

`geekom/strata/geometry.py` accepts only the two audited owner geometries.
`llama-compat` launches two native 512K slots and verifies the engine-reported
context and slot count before serving. It adds explicit `--rope-scaling yarn`,
`--rope-scale 2.0` and `--yarn-orig-ctx 262144` for this mode. Q3 weights, KV4,
6000-slot expert-cache budget, no MTP, 1024-token prefill chunks, prefix reuse,
and bounded 512 MiB conversation parking are retained. App/engine/Python files
remain under `~/strata` on the app filesystem; models and prepared pack stay on XFS.

A conservative preflight estimate is around 104 GiB (three 512K states including
the main session), slightly beyond the earlier literal 110 GB planning allowance.
This estimate charges every GGUF byte as resident. The native smoke instead
monitored whole-host nonavailable memory (`MemTotal - MemAvailable`) once per
second and would stop above 110,000,000,000 bytes or after six minutes. This is a
host pressure guard and an estimate, not an exact engine-only allocation meter.
It does not add CPU memory and UMA GPU memory as independent pools.

The two-slot smoke passed four short answers over two rounds. Engine-reported
context was 524288 and batch slots 2; load took about 42 seconds. The maximum
observed whole-host nonavailable estimate was 86.96 GB. Two authenticated public
gateway requests also passed. This proves allocation and short-answer serving,
not two simultaneous full-length 512K conversations or retrieval beyond 256K.

Evidence: `research/benchmarks/20261030-geekom-512k/`.

## B70 implementation and validation scope

The single-window mode retains the first 40 expert layers and PLE table on CPU,
`--no-op-offload`, Q4 KV, and the existing SYCL runtime. The total KV token count
stays 786432, as in three × 256K. One recurrent sequence costs less state than
three; the model's conservative estimate remains under the 31.89 GiB VRAM budget.
The new exclusive pool passes explicit YaRN 3× arguments to llama.cpp.

Evidence is written to `research/benchmarks/20261030-b70-768k/`. Native validation
checks one 786432-token slot and two 8K synthetic retrieval rounds, followed by
an authenticated gateway request. No claim of full 768K quality follows from this.

## Client publication and activation

The canonical OpenCode sources are `machine-setup/shared/agents/` and the three
`machine-setup/machines/{bigcachy,l-dev-ai,mini-mobile}/config/opencode.jsonc`
overlays. `geekom/strata/sync_clients.py` publishes both validated Geekom modes
and only whitelisted B70 Flash modes, preserves defaults and provider options,
and renders live settings on all three dev machines. It intentionally does not
run `opencode reload`: that can close active workspace runtimes. Reopen an idle
client if the new entry has not appeared.

Deployment drains admissions, waits for real native idleness, then tests and
switches. It never cancels another session. Smoke failure restores the earlier
profile; draining has a bounded deadline. The operator may restore the old modes
using the normal owner management interface after current work completes.

Use the bounded two-night plan in
[benchmarking-qwen-b70-and-gkm-2026-10-27.md](benchmarking-qwen-b70-and-gkm-2026-10-27.md)
for full-window retrieval, long-prefill fairness and sustained concurrency work.
