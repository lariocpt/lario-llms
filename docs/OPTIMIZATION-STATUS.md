# Optimization implementation checkpoint — 2026-10-05

The implementation is in progress. Geekom was released for testing; the Radeon
remains protected by the user's explicit hold. No Radeon stop, restart, recreation
or profile switch has been performed. Physical boot tests remain pending.

## Runtime and evidence

Geekom Flash Next is being evaluated at 3 × 245760 tokens with two reservations.
Per-request context is unchanged. Initial available RAM was 22–23 GiB; five equal
inputs reduced median long-prompt TTFT from 30.299 to 24.614 seconds and raised
decode from 22.36 to 26.88 tokens/s. Swap here is zram, not disk swap. The 30-minute
pressure/mixed-load observation and quality gates are still running/pending.

RTX Qwen's temporary 32k q8 GPU-KV test achieved 5.457-second median TTFT versus
8.236 seconds with the capacity preset; decode was 53.52 versus 8.31 tokens/s on
the long-prompt fixture. Observed VRAM headroom was about 2.7 GiB. The original
262144-token CPU-KV capacity profile remains in the registry. Client metadata must
be coordinated before any experimental GPU preset is promoted.

Actual prompt usage is 11036 tokens despite the legacy fixture name latency-8k.
Results are shared-service observations, with five repetitions per input. They
are initial measurements and do not replace the full promotion gates.

Ten tool-call/execution-followup cases passed on both RTX presets. Ten isolated
RAG retrieval/cited-answer cases passed using a disposable collection, with
cleanup verified. Real OpenCode completion passed. The corrected restricted
file-edit pilot passed. Earlier coding attempts were invalid: a missing explicit
workspace/config caused a misplaced owned fixture, then the evaluator rejected
valid dict.fromkeys. The owned misplaced artifact was removed; corrected runs
use an exact temporary path/config and a tested restricted pure-function evaluator.
The complete ten-case real OpenCode coding suite subsequently passed. All ten
32k tool cases and the 24576-token marker input also passed. Vision comparison,
additional contexts and the full contention matrices remain work.

## Implemented source

- Saved hardware resource presets, numbered selection, actual-process budgets,
  busy/held refusal, rollback and the tested native startup-lock fix.
- Resident-only latency/vision, tool, real OpenCode, RAG and long-context runners;
  memory/PSI/zram/VRAM telemetry. Evidence is in research/benchmarks/.
- Authenticated streaming admission with separate workload credentials, fail-closed
  reconciliation, drain/resume, disconnect and truncated-stream quarantine.
- Private backend configuration and staging; native deployment helper with rollback.
  The native helper refuses Radeon container deployment. Complete peer/caller
  credential integration and production canary validation are still pending.
- Per-owner authenticated Docker frontend overlays and activation-marker-aware
  startup sources. No marker or gateway has been activated. Reservations are
  currently advisory, not enforced.
- OpenCode's optional private credential/context fragment, and RAG's optional
  fleet-key header; no secret is stored in source.

## Retirement and completed checks

Bifrost's actual usage/client audit supports retirement. Its last successful chat
was August 7; recent chat calls failed. Only that container was removed. Active
compose/startup sources omit it and retain the other LLM/RAG services. Historical
ignored SQLite databases remain. Sanitized evidence:
research/bifrost-retirement-audit.json.

Cline CLI and VS Code extension provisioning are retired. The user npm package was
removed from both model hosts. Machine-setup renders OpenCode only; the desktop
post-installer no longer installs Cline or changes npm's prefix for it. The CLI
installer already had no Cline installation path and records the audit. Existing
Cline conversations/credentials were retained. Intel tools remain in OpenCode and
Hermes. Installer PRs 11 and 5 were merged and mesh-synced to l-dev-ai; mini-mobile
was unreachable and media's sync opt-out was respected.

All four machine-setup dry runs and affected Python/shell checks passed. Hermes'
real citation-gated ingest stored 252 BGE-M3 chunks; retrieval returned Cline,
Bifrost and Geekom checkpoint facts. Portainer's local and configured HTTPS status
reported 2.39.5 with server 1/1 and agent 2/2 replicas.

## Remaining completion gates

Finish comparable quality and 30-minute mixed workloads; promote only passing
presets. Complete all caller credentials and run a production admission canary
without a backend bypass. Apply the protected Radeon changes only after explicit
release. Ingest the final implementation and retrieve it again. Merge/sync each
remaining repo change, then run all four physical boot-order scenarios from the
canonical optimization plan, including Portainer and persistent KB recovery.
