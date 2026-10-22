# OpenCode fixed profiles and session identity

Current operation: [model controls/session identity](model-control.md) and
[MCP guide](mcp-guide.md). machine-setup owns all three overlays and the private
credential-preserving renderer. Select a fixed hardware-prefixed model; its
client context is server context minus 4096 tokens.

The default is regular Geekom Smart large capacity, 245760 server / 241664 client
tokens, five slots and Q8 KV. Radeon Qwen has 126976 client tokens; RTX Qwen has
61440. Mutable alias budgets no longer determine these limits.

The v2 plugin adds user-message/run, session, plugin instance and request kind.
Owners authenticate installations with scoped keys. The page cancels exact runs
through forced-command SSH and supported v2 plugin RPC/interrupt APIs. Stale run
or instance actions refuse interruption. No conversation database is edited.

`tests/check_opencode_identity.py` verifies real installed OpenCode headers and
interruption against a disposable fake model, without GPU inference. Existing
sessions predating the plugin may lack run identity until a new explicit user turn.
Changing context cannot reconstruct history already compacted.

## Historical home-repository watchdog incident — October 5

After those request tests, a persistent UI restart issue was investigated separately.
Logs showed `Event stream stalled`, health checks timed out, and clients replaced the service
roughly every 57 seconds. The server consumed ~100% of a CPU core and ~2.3 GB RSS while idle;
RTX stayed running and completed requests. A UI was rooted at `/home/lario`, with a home Git
repository created the previous day for RTX scripts. Adding a local exclusion for untracked
home directories stopped the stall; health checks then took 1–7 ms and 15-second heartbeats
arrived normally with a stable PID. At the user's request `/home/lario/.git` was subsequently
deleted, preserving home files and all project repositories. Another 70-second observation
confirmed stable health and heartbeats after removal. The model selector scripts contain no
OpenCode restart/reload commands.

The observations establish home-tree indexing as the operational trigger; the precise hot
function inside the compiled OpenCode binary was not profiled. Request success alone had not
proved the persistent UI was healthy. The fix was verified with both.

Source: host OpenCode logs and direct HTTP/process observations, plus the official
[client watchdog](https://github.com/anomalyco/opencode/blob/v2.0.22/packages/client/src/solid/connection.ts),
[service recovery](https://github.com/anomalyco/opencode/blob/v2.0.22/packages/client/src/effect/service.ts),
and [file search](https://github.com/anomalyco/opencode/blob/v2.0.22/packages/core/src/filesystem/search.ts).

## Geekom 512k configurations

Smart and Medium each add a `long-512k` fixed profile: 524288 server / 520192
client tokens, three slots, Q8 KV and explicit 2× YaRN. These replace the
two-slot IDs; other profiles and defaults remain unchanged. Three-slot runtime
validation and live client rollout await a safe idle deployment window. See [deployment and memory notes](geekom-512k-profiles-2026-10-22.md).

## Compact model labels

Labels put the decision-critical values first: `Geekom - 512k 3 slots - Qwen3.8
Smart …`. k means 1024 server tokens, so the existing 245760-token profiles show
240k and the 122880-token profiles show 120k. Names change without changing IDs,
contexts, slots or saved session model choices.
