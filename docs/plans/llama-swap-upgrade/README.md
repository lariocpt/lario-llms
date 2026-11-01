# llama-swap upgrade and native-router migration

Planning date: 2026-10-26. Status: **research and implementation plan only**. No runtime/configuration changes or deployment are authorized by these documents. Refresh the evidence when implementation begins.

## Decisions and order

1. **Phase 1:** upgrade the existing upstream llama-swap deployment to a verified, pinned upstream release; preserve the current Lario gateway, group routing and model behavior. Research baseline: v267. Do not introduce capacity-based eviction.
2. **Phase 2:** replace llama-swap with upstream llama.cpp router mode behind the Lario owner gateways, after proving lifecycle, occupancy, headroom and cancellation parity. Retain an explicit rollback to Phase 1. Do not create a llama.cpp fork to force compatibility.

Within Phase 2, investigate **MaximHQ Bifrost as common inference ingress and logging**, independently of the router migration. This is a conditional decision, not a commitment to deploy it and not a third migration phase. Native-router rollout must not depend on adopting Bifrost.

The local llama-swap executable identifies as upstream v233, commit `083e42105cb797b0bd9df174ab4dc8aa4a7e9c1a`, with `vcs.modified=false`. No llama-swap fork/source patches were found in this repository. The custom implementation is our owner gateway, admission policy, generated configurations and controls. Remote-host provenance is still an execution-time audit item.

## Reading order

- [Current state and compatibility contracts](01-current-state-and-contracts.md)
- [Phase 1: upgrade upstream llama-swap](02-phase-1-upstream-upgrade.md)
- [Phase 2: integrate the native llama.cpp router](03-phase-2-native-router.md)
- [Bifrost and logging investigation](04-bifrost-and-logging.md)
- [Acceptance, rollout and rollback](05-validation-and-rollout.md)
- [Research sources and delegation record](06-research-and-provenance.md)

## Completion criteria

Phase 1 ends when every enabled owner runs the pinned upstream swap artifact, contract and hardware acceptance checks pass, rollback has been demonstrated, and previously Off/stopped devices remain Off/stopped. A device that cannot be tested remains explicitly pending; it must not be counted as migrated.

Phase 2 ends when each migrated owner uses upstream native router mode with unchanged public model IDs, capacity policy, operator controls and client/run identity. All swap-specific production callers must be adapted before retiring swap. A failed compatibility gate leaves that owner on Phase 1 and blocks any claim of complete retirement.

Bifrost receives a written adopt/defer/reject decision supported by the experiments in its investigation document. Choosing direct ingress with central owner telemetry is a valid result.

## Defaults

- Preserve model weights, quantization, speculative decoding, context limits, slot reservations and disabled experimental profiles.
- Preserve public provider IDs, inference ports, client context metadata and management API semantics.
- Preserve durable Off, workload locks, registered-run cancellation and the separation of management/backend/inference credentials.
- No automatic retries, fallback to a different immutable profile, automatic residency eviction or background GPU benchmarking.
- All documented new engine interfaces, switches and artifact manifests are **proposed implementation**, not existing capabilities.
- Documentation can drift from source and production. Inspect the current working tree, owner registry and effective units before executing. Do not overwrite unrelated dirty work.
