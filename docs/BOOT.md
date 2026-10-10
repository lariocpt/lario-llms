# Model startup and host ordering

Each model host starts from local weights on its XFS filesystem. User systemd
units require that mount and both hosts have user lingering enabled. Intel uses
four enabled native units; RTX uses the enabled native `rtx5080.service`. Geekom
uses the enabled native `llama-swap.service` supplied by machine-setup. Radeon is physically removed and agent-llm is stopped with restart=no; the
xt boot profile is disabled. Supporting containers use Docker restart policies and the infra/Hermes reconciliation
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
persistent-data and Portainer checks. Bigcachy's individual reboot passed below;
the other three scenarios remain pending.

On 2026-10-06 the user released the Radeon testing hold and requested bigcachy's
recovery reboot after compaction. The recorded preflight is
research/reboot-checkpoint-20261006.json. Geekom stays online for this first test.
After boot, verify a changed boot ID, healthy NVIDIA reporting and actual CUDA
offload, saved GPU selections, all four Intel services with real workload calls,
Chroma persistence/retrieval, OpenCode inference and Portainer service health.
A single-host reboot does not complete both cold-start order tests.

Bigcachy's reboot with Geekom online passed on October 6: changed boot ID,
automatic native/container startup, all three chat completions, actual RTX
GPU memory use and healthy NVIDIA reporting, four Intel workload calls,
OpenCode default/RTX completion, 283 retained/retrievable KB chunks, eight
intact Hermes databases and Portainer's 1/1 server plus 2/2 agents. The
shutdown NVIDIA memory-cleanup warnings are preserved in
research/rtx-reboot-shutdown-20261006.json; original bus-loss cause is unresolved.
The Geekom reboot and both cold-start order tests remain pending.

Portainer was checked on 2026-10-05: its Swarm server had 1/1 running replicas and
its global agent service 2/2. Both local and HTTPS `/api/status` returned version
2.39.5. This verifies service/API health, not an authenticated audit of every managed
endpoint.

A fresh October 6 Portainer check returned HTTP 200 and version 2.39.5, with
server 1/1 and agents 2/2. This confirms current service/API health. Radeon
removal does not change the retained Intel/RTX startup units; start_all.sh now
respects the disabled xt profile instead of forcing the removed device online.

The current boot-test inventory excludes Radeon, which the user removed. All
Hermes agents remain paused and must stay stopped through boot tests. New RTX
headroom/profile-routing changes and any admission activation require fresh
startup checks; the earlier individual reboot proves the earlier configuration.

RTX admission is now enabled as lario-admission@rtx5080.service. Its native
drop-in moves llama-swap to authenticated loopback :11445, while the gateway
owns :11435 and the marker-aware Compose helper retains the vision credential
template. Its selected 64k Qwen uses validated GPU q4 KV. The periodic monitor
loads owner runtime routing and uses the public auxiliary budget for active
probes; it skips busy/unknown occupancy. These source changes still need fresh
physical boot evidence. Geekom's warmup wrapper now uses its owner controller,
so later admission activation does not leave boot warming on an unauthenticated
public port. Paused Hermes and the disabled Radeon must stay stopped.
