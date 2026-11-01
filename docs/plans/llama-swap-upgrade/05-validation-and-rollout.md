# Acceptance, staged rollout and rollback

## Validation layers

Planning performed no GPU probes, load/unload operations, service changes or runtime deployment. The checks below are implementation acceptance work. Do not run production profile loads merely to validate documentation.

**Layer 1 — source and policy tests.** Run existing admission, fixed/shared-serving, lifecycle, client-control, deploy, container and boot tests against the implementation baseline. Preserve existing expected policy outcomes. New tests cover changed backend contracts and lifecycle races, not assertions duplicating implementation internals.

**Layer 2 — real protocol with fake workloads.** Test v233 versus the selected Phase 1 swap binary using a CPU-only fake child; test the Phase 2 adapter with recorded upstream response fixtures and controlled fake native endpoints. Start an actual pinned router without production model weights to validate flags, presets, auth, catalog/control refusals and startup behavior. This proves parsing/protocol, not GPU behavior. A small disposable CPU model may be used only in an isolated implementation test if needed to verify actual child startup/argv/monitor dispatch.

**Layer 3 — bounded real owner smoke.** After guarded drain, validate the existing selected enabled model on one owner at a time. Reuse established prompts/images and conservative output caps, including one representative tool exchange and a nontrivial image for vision profiles. Do not introduce new model/quantization/context choices or re-enable disabled experiments. Long-context correctness/quality and memory acceptance use existing validated hardware protocols; they are explicit scheduled work, not inferred from tiny prompts.

## Required scenario matrix

| Scenario | Required result |
| --- | --- |
| No/invalid inference credential; management key used to infer | Same public refusal as before; no load/forward |
| Registered clients and fleet/interactive/auxiliary roles | Key-derived identity and reservations preserved; one installation cannot cancel another's run |
| Unknown/disabled/public-vs-backend ID | Consistent refusal, no backend autoload or profile substitution |
| Fixed vs shared catalog | Identical public IDs, context metadata and allowed endpoints; compatible variants share exactly one backend |
| Exact geometry | Observed weights/projector/drafter, cache types, runtime context and parallelism match profile; mismatch fails closed |
| Full slot occupancy plus monitor | Overflow refuses; real occupancy remains readable; no idle inference from a 429/time-out |
| Shared context reservation | Atomic allocation, retained until backend work ends; no undercharging tools/images or unsupported multi-completion |
| Shared headroom and coexistence | Missing/ambiguous sensor refuses load; measured manifest matches observed child; no unrelated residency eviction |
| Stream success, error before headers, error mid-stream | No extra retries/duplicate tools; terminal outcome accounted once; no stuck admission reservation |
| Disconnect and exact-run cancel | Backend activity reconciled, same-backend healthy work remains usable; stale run/instance cannot interrupt new work |
| KV erase | All slots idle; expected acknowledgements; uncertain erase blocks unsafe allocation |
| Load collision / unload during activity | Owner exclusion and revision checks prevent unsafe operation; no active allocations lost |
| Child crash / router crash / gateway restart | Unknown residency reported until reconciled; no manifest reuse from stale generation; bounded recovery |
| Preset refresh with resident sibling (Phase 2) | Unchanged sibling survives, including active inference; inability blocks shared-owner migration |
| Native autoload/sleep/LRU (Phase 2) | Read/monitor cannot load; public request cannot override; explicit owner policy controls all residency |
| Durable Off, paused, cold and stopped states | Preserved across deploy, rollback and tested reboot; no unsolicited warmup |
| GPU workload lock, absent eGPU or model store | No serving start or resource theft; explicit unavailable/deferred owner |
| Container namespace and remount | Correct executable hash/image actually running; private child ports remain private; occupancy works under load |
| Upgrade failure / rollback failure | Original artifact restored when possible; otherwise admission stays closed with actionable recovery evidence |
| Bifrost identity/protocol/logging | Separate matrix and canary-string/retention tests in the investigation document |

Run only the relevant test groups after each change; perform full policy suite and required owner acceptance before rollout completion. Broad reruns are justified by changes/failures, not ritual repetition.

## Shared rollout transaction

Both phases use: snapshot -> owner/workload exclusion -> close new admission -> wait for tracked requests **and actual slots** -> recheck state -> change one owner -> verify process/config -> bounded smoke -> restore prior admission state. The drain timeout is 15 minutes; expiry leaves the old deployment intact and restores its prior pause setting. Do not force cancellation to meet a rollout schedule.

For failures after cutover, keep admission closed, reconcile actual child activity, and restore the previous artifact/config/engine only after confirming idle. Never run old and new engines on the same GPU simultaneously. Do not restore a stale workload lock, overwrite a concurrent policy revision or power on an Off device. Backups containing keys are private and never copied into the public plan/evidence directory.

## Owner order and observation defaults

Actual owner enablement/placement/device presence is established immediately before rollout. Default order:

1. RTX5080 native exclusive canary, only when idle and with an accepted existing profile.
2. RTX3060Ti container canary, if attached/available; otherwise defer it explicitly and test Radeon as the container path when safe.
3. Radeon7900XT container owner, if available; retain physical identity/dock guards.
4. ArcB70 shared/native owner after its current experimental work is stable and the shared gates pass.
5. Geekom shared/native owner last to protect interactive capacity.

Do not choose a disabled experimental profile to obtain a canary. An unavailable owner is pending and does not block unrelated safe staging, but blocks the claim that all owners are migrated. If an owner's runtime/model build lacks the required upstream router, leave it on Phase 1 rather than changing its model behavior.

After immediate checks, observe each new canary for at least 30 minutes of representative use before advancing. Require 24 hours of normal use with no protocol/admission/cancellation regression before migrating the corresponding remaining runtime family. Require seven days after the last accepted Phase 2 owner before removing swap production integration. Bifrost's 48-hour pilot starts after native-router stability and is independently reversible.

## Evidence and stop conditions

Record per-owner: implementation/source revision, registry/generated-config hashes, executable/archive/image digests, effective sanitized unit/container command, original lifecycle state, exact profile/backend IDs, test outcomes, startup/TTFT/inference observations, peak memory/reserve evidence, rollback rehearsal and unresolved limits. Record actual results and counts, not just an assertion that a command ran.

Stop expansion for any wrong identity/profile/context, silent eviction, workload-lock/Off violation, content leakage, unexpected model load, inability to observe occupancy, lost cancellation, repeated unexplained upstream errors or unsafe memory behavior. Leave healthy unmodified owners serving normally. A failed owner remains paused/unavailable until recovery is proven; do not globally disable healthy same-profile work without evidence.

Deployment acceptance is a per-owner result. Static tests, a successful liveness endpoint and a catalog listing never establish that a real model can load or infer. Source-only/unexecuted checks remain clearly marked pending.
