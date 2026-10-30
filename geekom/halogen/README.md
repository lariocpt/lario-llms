# Halogen on l-dev-ai

Halogen 0.18.19 is launched on demand by the existing Geekom owner and
llama-swap, through `llama-compat`. It owns the integrated GPU exclusively. The older Geekom models have been retired. Do not start a second standalone container alongside it.

Applications and state live on btrfs: `~/halogen/venv`, this launcher, and
`~/.local/share/containers/storage`. Only downloaded model assets live on XFS:
`/mnt/AI_Models/halogen/qwen38-flash-next`, mounted read-only in the container.
Image digest: `sha256:f4ee69cafd334f5fed1173e998550dea00505e0df2bb3cb90b60d7a7aa1332f4`.

OpenCode offers Halogen 128K and 256K choices under `geekom`; defaults are
preserved. Both share four stream slots and a 524288-position KV pool. Owner
admission reserves the complete selected window, permitting four 128K requests,
two 256K requests, or one 256K plus two 128K requests. Output fits inside that
window. Native per-request maximum is 262144, without YaRN extension. This is
allocation policy, not evidence of full-window retrieval quality.

The v2 checkpoint includes MTP; prefix caching is enabled. Thinking defaults to
medium and may be controlled per request. Native vision is enabled and tested;
the shared owner gateway retains its existing text-input contract and client
attachment handling. Private Halogen API: `127.0.0.1:18731`, authenticated with
the existing backend key. Its engine port is never published. The adapter
provides authenticated template/token counting and translates native aggregate
occupancy into the gateway's probe format, failing closed on unknown state.

## Memory locking

`HALOGEN_WEIGHTS_LOCK=1` needs an unlimited hard memlock limit in the actual
launcher ancestry. Rootless Podman silently clamped its requested limit to 8 MiB
before the administrator step. The flag alone did not lock the weights.

On 2026-10-31 the user ran `sudo python3 geekom/halogen/install-memlock.py` on
l-dev-ai. This installs scoped user-manager and llama-swap memlock drop-ins and
raises the live manager/launcher limits without logging out or rebooting. After
a guarded idle reload, the engine confirmed 62.11 GiB checkpoint plus 0.84 GiB
vision locked; `/proc/meminfo` reported about 62.9 GiB Mlocked. No BIOS, kernel
command line, IOMMU or compaction sysctls were changed.

The engine reports 89.8 GiB for weights, working memory and KV; startup left
about 31 GiB for the host and lookup-table cache. The 47.7 GiB n-gram table is
paged, not entirely held resident. Validate actual host headroom before enlarging
the KV pool or adding other workloads.

## Validation and rollback

Evidence: `research/benchmarks/20261031-geekom-halogen/`. Four short concurrent
coding requests, cache reuse, forced tool call, complete SSE streaming,
cancellation/recovery and native vision passed. The four short requests took
0.77–1.10 seconds after locking, versus 2.90–3.81 seconds before; generation
reported no queue evictions after locking. These are smoke tests, not sustained
throughput, long-prefill fairness or full-window quality benchmarks.

Use `shared/serving/control.py geekom status` and the normal owner interface.
The user subsequently retired the old Geekom models and weights; the old Strata
profile is no longer a rollback option. Preserve the retained Radeon, RTX and B70
models. Configuration/evidence backups remain under `~/halogen`, but they do not
restore deleted weights.

Existing tool histories are normalized with `tool_parse.normalize_messages`
extracted from the same pinned image into `~/halogen/vendor/0.18.19` before
rendering/token counting. This fixes OpenAI JSON-string arguments and developer
roles during model switches; a synthetic multi-turn history matched native
Halogen's 103 prompt tokens exactly without changing user session data.

`sync_clients.py` adds these two choices to the three client machines through
the canonical machine-setup renderer, preserving defaults, credentials and
existing choices without restarting active workspaces. Installed dependency
versions are recorded with the validation evidence.
