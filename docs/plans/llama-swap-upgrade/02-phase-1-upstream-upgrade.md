# Phase 1 — Upgrade to upstream llama-swap

## Objective and fixed choices

Upgrade upstream v233 to upstream v267 (research baseline dated 2026-10-26), without a fork, new eviction policy, model build upgrade or client migration. On the execution date, recheck releases and advisories. Use v267 unless a verified defect/security issue requires a newer stable release; record any changed target and rerun the entire contract matrix for that version. Never install an unpinned `latest` artifact.

Retain generated legacy top-level `groups`, current fixed/shared group values, per-model concurrency limits, backend auth and long-load handling. The v267 parser explicitly supports legacy groups and normalizes them. It rejects configurations mixing legacy top-level `groups`/`matrix` with the new `routing.router` block. **Do not add that block in Phase 1.** Do not adopt or test capacity eviction on production owners during this upgrade.

Primary references: [v267 release](https://github.com/mostlygeek/llama-swap/releases/tag/v267), [v267 configuration](https://github.com/mostlygeek/llama-swap/blob/v267/docs/config.example.yaml), [compatibility parser](https://github.com/mostlygeek/llama-swap/blob/v267/internal/config/load.go), [v233–v267 comparison](https://github.com/mostlygeek/llama-swap/compare/v233...v267).

## 1. Establish exact deployment inventory

For every owner in the inventory, record registry host, device identity, unit/container name, effective command and environment-file paths, binary realpath/inode/hash/version, current profile/backend IDs, process state, enablement, durable Off/paused state, workload locks, and which services share each binary path. Collect metadata without copying prompt logs or exposing credentials.

Use read-only effective `systemctl --user cat/show`, container inspect and version/hash inspection on the actual owner. Reconcile registry placement with live service placement. Existing containers may bind an older inode even when a host path has been replaced. An inactive/detached device is recorded as pending, never powered on merely to complete an upgrade inventory.

Check the working tree first. Implement later in an isolated branch/worktree containing the agreed source state; do not overwrite current unrelated B70/shared-serving changes. The planning snapshot is not a deployment baseline.

Deliverables: owner inventory, shared-binary dependency map, compatibility checklist against all intervening release notes, selected artifact manifest and source/config snapshot hashes. Review process termination, config reload, API auth, inference semaphore, streaming/cancellation and monitoring changes across the version interval; a short release summary is insufficient.

## 2. Stage reproducible artifacts and installer support

The official Linux AMD64 asset for the research target is:

- Filename: `llama-swap_267_linux_amd64.tar.gz`.
- Published archive SHA-256: `5e57a83418554ed4c4be1247819c0dd2ba7deb2c44f334fb5da3afec51b2d41c`.
- Published checksum file: `llama-swap_267_checksums.txt`.

Resolve assets from the official release metadata; compare the archive against the official checksum file and release digest before extracting. Reconfirm these values at execution. Record archive hash and extracted executable hash separately; do not apply the archive hash to the executable. Preserve source URL, version, commit, architecture, extraction layout and verification time.

Add one shared, idempotent artifact provisioning path, consumed by native and container owners. Stage versioned binaries on the appropriate model XFS store (`/mnt/AI_Models` or `/mnt/xfs/AI_Models`), retain the old artifact, and make the selected executable path explicit per owner. Preserve existing container library/runtime images. Do not modify a shared mutable binary path in place while unrelated units depend on it.

Where effective units share `~/.local/bin/llama-swap`, use per-owner overrides pointing to a versioned artifact for canaries. For Podman owners, change the planned read-only bind source only for the owner being migrated and recreate only that container after draining. A host-side symlink replacement alone does not prove the running container changed. Keep a complete dependency map until all consumers have migrated; changing the common symlink is the final cleanup, not the first rollout step.

Do not assume a release has a config-validation CLI flag. Verify `--help`; if absent, validate in an isolated instance using test commands and temporary paths. Never run a generated production config with real GPU commands merely to check YAML parsing.

## 3. Preserve behavior and narrow new surfaces

Run both the old and new binaries against the same temporary configuration and CPU-only fake OpenAI backend. The fake process must expose health, slots, template/tokenization, controllable startup delay, streaming, cancellation and failure responses; no real weights or GPU allocation.

Verify legacy groups exactly, including shared groups where automatic swapping is disabled. Validate `/running` fields used by our code, management unload behavior, authenticated passthrough, concurrency rejection, process cleanup, reload behavior and failed-start recovery. Compare normalized results, not incidental timestamps/log wording.

Review v267's request/response capture and new administrative/UI/help-agent surfaces. Configure `captureBuffer: 0` in the backend generator so the upgrade does not add in-memory prompt/response capture. Keep the private backend on authenticated loopback and do not expose its UI/admin endpoints through the public gateway. Disable unused UI/help capabilities where the pinned schema provides a supported switch; otherwise prove they remain unreachable to inference clients. Keep persistent activity/content storage disabled unless separately designed in the logging investigation.

Retain monitoring that bypasses the inference semaphore. A one-slot model must not become uninspectable solely because the sole slot is busy. Test shared idle-KV cleanup separately: it uses swap passthrough and must refuse or fail closed if occupancy cannot be proven.

## 4. Implement a guarded owner upgrade transaction

Extend deployment support rather than executing an unguarded restart:

1. Acquire the same owner lifecycle/workload exclusion used by control operations. Persist an upgrade-in-progress state or equivalent guard preventing concurrent start/stop/load and deploy actions.
2. Snapshot original Off/paused/enablement state and private configuration metadata; protect backup contents with mode 0600. Pause owner admission before checking idle, so new requests cannot race the check.
3. Wait up to 15 minutes for tracked requests and real backend slots to become idle. Do not cancel work automatically. Timeout, unknown occupancy, transition, missing dock or another workload lock aborts the transaction and restores pre-upgrade admission state.
4. Recheck residency, lock ownership and state revision under exclusion. Back up selected artifact/config/units and last ready profiles. For an originally stopped/Off owner, stage only; preserve stopped/Off state.
5. For an active idle owner, stop only that owner's serving backend, select the staged artifact, reload affected unit metadata if needed and start cold. Keep public admission paused. Recreate its container if required to remount the binary; do not run a generic compose-up.
6. Verify actual running process/container artifact provenance and keyed backend health/config compatibility. If the owner had a ready profile, explicitly reload that exact enabled profile and inspect geometry/slots before resuming. If previously cold, keep cold; do not invent a preload target.
7. Run the bounded real smoke matrix described in the validation document while external admission remains paused. Remove the guard and restore the original admission state only after acceptance. A previously paused owner remains paused.

Any failure after stopping enters rollback before reopening admission. Recovery errors leave admission closed and report the retained backup/artifact paths. Never report success merely because `/health` or `/v1/models` returned 200.

## 5. Rollout and acceptance

Use the sequence and dwell periods in [validation and rollout](05-validation-and-rollout.md). Separate native, shared-pool and container canaries; no successful native canary implies container acceptance. Detached hardware remains deferred. Protect interactive Geekom workloads by migrating them late.

Every accepted owner must demonstrate: expected binary hash/version, identical public catalog and geometry, preserved role/client identity and reservations, overflow rejection, genuine backend occupancy under load, complete stream termination, disconnect/cancellation reconciliation, correct Off/workload-lock behavior, and successful restoration to the prior artifact in a rehearsal.

If a source adjustment is needed for a changed upstream response, implement a narrow compatibility normalization with explicit fixture coverage, retaining legacy behavior until all owners migrate. Do not fork upstream to accommodate a response-shape assumption.

## Rollback and exit evidence

Pause/drain exactly as for upgrade; restore the old artifact selection, generator/config snapshot and effective unit/container bind; recreate only the affected container if needed. Confirm old process provenance and actual idle/ready state. Reload only the previously enabled exact profile if appropriate, then restore original paused/Off state. Stop immediately if restoring a previous profile would violate a new device/workload condition; keep the owner unavailable and report why.

Write a per-owner acceptance record with before/after artifact hashes, source revisions, test results, rollout times, failures and rollback outcome. Phase 1 completes only after the full acceptance matrix passes for each migrated owner. Keep the old artifact and backup until Phase 2 retirement criteria are satisfied.
