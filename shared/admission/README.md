# Request admission — implementation and rollout

Source implementation is experimental; no gateway is currently active. Existing
fleet budgets remain advisory. Tests exercise reservation contention, credential
classification, alias sharing, unavailable hosts, startup reconciliation, drain,
disconnects and truncated streams with real loopback HTTP servers.

Each hardware owner runs a streaming aiohttp gateway on its existing public port.
The model proxy moves to an authenticated loopback port, child servers bind only
loopback and require a separate key file. Interactive, fleet, auxiliary and
management keys differ. Geo reserves two slots; fleet and auxiliary together may
use the remainder. RTX admits only auxiliary work. A concrete request cannot swap
models. Switching must drain admission and use the owner controller while idle.

Prepare artifacts without touching a service:

```bash
python3 shared/admission/provision.py geekom --model qwen38-flash --preset balanced --listen 127.0.0.1 --output /tmp/geekom-admission
```

For production, listen on 0.0.0.0 with authenticated admission. A wildcard
listener tolerates direct-link, LAN and tailnet addresses appearing in any order;
binding every currently assigned address would prevent startup while a peer or
network interface is absent. The private backend remains loopback-only. Install
`requirements.txt` into the owner's XFS admission venv. Private artifacts are mode
0600. Merge client fragments privately into ~/.config/lario-admission/clients.json
on online client hosts, then run machine-setup's OpenCode renderer. Keep secrets
out of Git and avoid mounting the entire credentials directory into containers.

Before activation, verify every current caller: OpenCode on online hosts, RAG's
`LARIO_GEEKOM_FLEET_KEY` in private compose environment, and each enabled Hermes
primary/auxiliary route. Parked agents need the corresponding source/deploy
credential integration before they can start. Preserve the supported Hermes
context floor when choosing a GPU preset; a 32k chat profile is unsuitable for
Hermes primary inference. No renderer/client rollout is inferred from artifact
preparation. Do not activate a gate until these callers have been audited.

`deploy.py <prepared-directory> --dry-run` checks current registry, owner, holds,
idle inference, credentials and the owner's rendered OpenCode config. Native
activation has file rollback and changes only its owner service. RTX also changes
only the vision DNS frontend; the Radeon activation is deliberately refused by
this native tool and requires its container rollout after the user's hold is
released. It does not claim to verify all peers automatically. The activation
helper and complete caller rollout still require a production canary test.

The per-owner backend drop-ins persist across reboot; admission units restart on
failure and report zero ready budget until the backend is ready and idle. Update
all automatic compose sources to retain the matching frontend overlay before
production activation; the broad opt-in docker-compose.admission.yml is not used
by normal startup. Physical boot testing and bypass checks are separate gates.

Use `shared/fleet_budget.py` for the live capacity snapshot. A gate's unavailable
budget never falls back to guessed registry capacity. Legacy proxies are clearly
labelled advisory and are used only when /budget is absent (404).

The fleet budget also enforces Hermes' primary-context floor: a server window
below 68096 tokens (64000 client tokens plus 4096 margin) advertises zero primary
fleet capacity. Such GPU presets remain interactive-only on Radeon; RTX's small
window is still usable for bounded auxiliary tasks. `modelctl <hardware> resume`
reopens a gate left drained by an aborted busy switch after work has ended.

`canary.py` runs a separate loopback-only shadow gateway with real bounded
requests and occupancy/cancellation checks. It never moves the public listener
or changes a model. A shadow pass is not production bypass prevention.

Hermes deployment uses agents/deploy/render-hermes-config.py and private
~/.config/lario-admission/fleet-clients.json. Only the relevant primary fleet
credential is written to the existing private agent .env; generated YAML carries
${LARIO_MODEL_FLEET_KEY}, which the installed Hermes config loader expands.
This helper runs on each normal deploy and therefore follows lario-fleet [m].
Staging that source does not restart agents or activate a gate.

Production entrypoint readiness also checks local RTX device health through a
read-only NVIDIA probe, with a five-second success cache. A ready proxy or a
successful short response does not override a failed device check. Device fault
budgets report zero, and inference fails closed. Unit tests inject device state;
no physical GPU is required for those tests.
