# geekom7900xt — Geekom external Radeon

The physical RX 7900 XT (UUID `255c7a14946751e2`) belongs to `l-dev-ai`,
connected through the spare M.2 NVMe slot. This is the sole Radeon provider.
The Winmax and gkm placement names are retired; their laptop files are archived
under `attic/7900xt-laptop/`.

`models.json` owns the profiles. Use `./geekom7900xt list` and
`./geekom7900xt config qwen3.8@fast-128k --experimental` to generate the backend
configuration. Public admission listens on port 11436; the backend binds only to
127.0.0.1:11446. Weights, Podman storage, the admission venv and the pinned
`bin/llama-swap` binary belong on `/mnt/AI_Models` (XFS).

The runtime verifies host ownership, the physical GPU UUID and ROCm compute;
CPU and iGPU fallback are refused. `systemd/geekom7900xt.service` starts it.
`machine-setup/shared/models/install-lifecycle.sh l-dev-ai` installs the units
only after private credentials and the staged binary are available.

Runtime acceptance remains pending: this editing session exposes model storage
read-only and denies access to the user systemd bus. A successful repository test
is not a live inference check. See the cutover record in
[the transition guide](../docs/hardware-transition-2026-10-23.md).
