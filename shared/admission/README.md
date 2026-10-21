# Authenticated fixed-profile admission

All three public model gateways are active. With `LARIO_FIXED_PROFILES=1`,
`server.py` runs the coordinator in `shared/serving/gateway.py`; the older
`Admission` class remains only for compatibility tests and migration.

Each owner exposes its public port and keeps its keyed llama-swap/child backend
on loopback. Interactive, fleet, auxiliary, management and backend keys differ.
Registered OpenCode keys further identify the three client installations. Client
identity comes from the key, never a hostname header. Old role keys remain
accepted for other consumers without trusted OpenCode run control.

The coordinator loads exact immutable profiles only on idle hardware. Busy
profile changes refuse; same-profile requests share available capacity. Geekom
reserves two interactive slots, Radeon zero, RTX admits its auxiliary class.
Disconnect reconciliation reads real occupancy and must not globally block
healthy same-profile inference. Unknown occupancy blocks unsafe activation.

Durable On/Off, profile admission controls, request cancellation and idle preload
use management-only versioned endpoints. Public budgets are sanitized. A separate
operator page uses owner management keys; browsers and inference clients never
receive them. Off blocks reboot startup and ordinary model requests.

See [model controls/session identity](../../docs/model-control.md),
[fixed catalog](../serving/catalog.py), and [boot behavior](../../docs/BOOT.md).
Private owner configuration lives in `~/.config/lario-admission/<hardware>.env`;
registered keys live in `<hardware>.clients.json`. Client fragments remain private
mode-0600 `clients.json` files. State and disabled markers live on model XFS.

Use `shared/serving/deploy.py` for initial owner migration; it checks idle state,
backs up private/config/unit files and preserves previously stopped hardware.
Use `shared/serving/provision_control.py` for operator/client registration.
Do not deploy the old single-profile provisioner over the fixed serving setup.

Current tests cover authenticated admission, fixed geometry, shared activation,
capacity, interrupted streams, actual slot reconciliation, credential-derived
identity, unavailable monitoring and Off/workload lock protection. Real OpenCode
identity/control checks use a fake local backend and disposable idle sessions;
they do not benchmark or load a GPU.
