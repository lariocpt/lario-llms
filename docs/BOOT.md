# Model startup and host ordering

Each model host starts from local weights on its XFS filesystem. User systemd
units require that mount and both hosts have user lingering enabled. Intel uses
four enabled native units; RTX uses the enabled native `rtx5080.service`. Geekom
uses the enabled native `llama-swap.service` supplied by machine-setup. Radeon and
supporting containers use Docker restart policies and the infra/Hermes reconciliation
scripts use the explicit bigcachy and Intel compose overrides.

Geekom's `ExecStartPre` renders the saved selection from the hardware registry,
including pinned local Q8/Q4 paths. Its background warmup addresses the `geekom`
alias, so a stale state filename cannot warm a different model. Geekom startup
does not require bigcachy to be reachable. RTX warms its hardware alias after proxy
startup, with a startup budget matching the model loader's timeout.

Intel exports are local, Hugging Face offline mode is enabled, and no model alias
or peer host participates in startup. The old Intel containers were removed so
native services are the only Intel workloads that can return after a reboot.

Client MCP discovery is offline: clients can start before bigcachy and retry actual
work when its services are reachable. Hermes boot preflights a remote coding host
with warnings rather than preventing local services from starting. The l-dev-ai
watchdog accepts any registered Radeon model, rather than requiring Muse to be
resident, and reconciles through the correct compose files.

Verification covers enabled units, local mount dependencies, lingering, registry
generation, hardware-alias warmup and discovery with an unreachable Intel host.
Actual host reboots were not performed while users had active inference requests.

The user requested real autostart testing at the end of the optimization implementation.
The [final-stage test matrix](OPTIMIZATION-PLAN.md#final-stage-real-autostart-and-boot-order-testing)
covers individual reboots and both host startup orders, with actual inference, client,
persistent-data and Portainer checks. Those physical tests remain pending.

Portainer was checked on 2026-10-05: its Swarm server had 1/1 running replicas and
its global agent service 2/2. Both local and HTTPS `/api/status` returned version
2.39.5. This verifies service/API health, not an authenticated audit of every managed
endpoint.
