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

Qwen uses a 64-token physical microbatch (`-ub 64`), with logical batch 2048,
one slot, Q8 KV and the same 131072-token context. On this Geekom, an uncached
2577-token diagnostic prompt took 7.34 seconds with microbatch 64 versus
117.11 seconds with 512. This is a short prompt-ingestion comparison, not a
full-window or sustained-load validation. See the
[measurements](../research/benchmarks/20261025-geekom7900xt-microbatch.json).

The runtime verifies host ownership, the physical GPU UUID and ROCm compute;
CPU and iGPU fallback are refused. `systemd/geekom7900xt.service` starts it.
`machine-setup/shared/models/install-lifecycle.sh l-dev-ai` installs the units
only after private credentials and the staged binary are available.

The backend is optional at boot: its `ExecCondition` checks the registered card
before configuration generation or container startup. An absent or unresponsive
card returns status 1, so systemd skips the backend without treating it as a
failed service. CPU and integrated-GPU fallback remain forbidden. The admission
gateway can stay available to report unavailable capacity; it does not start a
model by itself. Manual Off intent is also preserved by the recovery watcher.

The 2026-10-25 boot journal confirms successful ROCm enumeration and backend
startup, followed by a loaded Qwen profile and an HTTP 200 chat completion.
All three development clients authenticate successfully. That boot also
recorded intermittent PCIe identity reads and AMD GPU errors, so sustained
inference stability and a physical boot without the dock remain pending.
See [the verification record](../docs/geekom-egpu-verification-2026-10-25.md)
and [the transition guide](../docs/hardware-transition-2026-10-23.md).
