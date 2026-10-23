# Radeon relocation and Arc B70 preparation

## Requested topology

| Name and folder | Host | State | Storage |
| --- | --- | --- | --- |
| `winmax7900xt` | cachyos-mini-mobile | Current Radeon placement, retained during transition; live provider remains `7900xt` | `/mnt/xfs/AI_Models` |
| `gkm7900xt` | l-dev-ai | Planned placement of the same Radeon via the spare NVMe slot | `/mnt/AI_Models` |
| `arcB70` | bigcachy | Awaiting installation alongside the RTX 5080 | `/mnt/xfs/AI_Models` |

The two Radeon names represent alternative placements of **one physical card**,
not additional concurrent capacity. Keep the laptop placement until the Geekom
placement works and its clients have migrated. `geekom` continues to mean the
Strix Halo Vulkan service, independent of its proposed external Radeon.

The placement manifests are preparation data, not active runtime registries.
Current `7900xt` routes, credentials, sessions and immutable IDs remain operational.
No gateway restart, download, model switch or client update is part of this staging.

## Candidate registries

Generate candidates from the authoritative Radeon registry, avoiding a second
copy of model parameters that could drift:

```sh
python scripts/prepare_placement.py winmax7900xt > /tmp/winmax7900xt.json
python scripts/prepare_placement.py gkm7900xt > /tmp/gkm7900xt.json
```

Both preserve Muse 128k/3 slots, Muse DFlash 128k/2 slots and Qwen 128k/1 slot,
their pinned ROCm image and Q8 target KV. New placement-qualified immutable IDs
are distinct. Display labels put context and slots before the model description.
Candidate registries cannot yet be passed to production deployment: CLI choices,
runtime storage paths, systemd, admission, credentials and fleet/client maps still
require the coordinated activation below. Arc registry generation deliberately
refuses until its runtime and models are verified.

## Radeon activation after connection

1. Drain the old placement, wait for idle and persist Off. Do not force-cancel
   active work without authorization. Retain the old weights and service for rollback.
2. On l-dev-ai, confirm the spare M.2 slot/adapter, power and link enumeration.
   Match vendor/device, physical unique ID `255c7a14946751e2` and >=19 GB VRAM
   using the existing Radeon detector; never select the internal Strix Halo GPU.
3. Prepare the XFS model paths, dedicated Podman storage and pinned ROCm image.
   Existing `7900xt/runtime.py` hardcodes the laptop's `/mnt/xfs/AI_Models` paths
   and old credential filenames: parameterize these before installing the new unit.
   Probe ROCm on this APU+dGPU host, bind compute to the registered unique ID,
   and refuse CPU fallback. Do not stop the independent Geekom Vulkan service.
4. Register `gkm7900xt` and transitional `winmax7900xt` consistently in modelctl,
   catalog, provisioning, control panel, MCP, fleet budgeting and machine-setup.
   Provision separate consumer/backend/management credentials and host endpoints.
   Keep the old `7900xt` route pinned to a single authoritative placement during
   migration; never auto-failover to another context or silently reroute a busy run.
5. Enforce placement exclusivity during provisioning: first persist the old
   placement Off, remove its fleet capacity and revoke its activation credentials,
   then enable the new placement. Fail closed if the old placement's state cannot
   be verified. `exclusive_with` in the manifest documents this requirement;
   production enforcement is not implemented by the preparation generator.
6. Test each model with a short authenticated request, native slot geometry,
   missing-card boot, durable Off and startup in either host order. Then generate
   and reload OpenCode settings on all three development machines. Existing
   sessions need an explicit model migration; placement IDs are intentionally new.
7. Update the Hermes KB, publish and verify retrieval after deployment. Deprecate
   `winmax7900xt` only after client and session audits show it is unused. Model
   deletion remains a separate audited action.

## Arc B70 activation after installation

Use `arcB70` exactly as the folder and intended hardware/provider name. It is
separate from Bigcachy's Intel CPU/iGPU/NPU services. Intel's reference Arc Pro B70
has 32 GB GDDR6, device ID `0xE223` and PCIe 5.0 x16; verify the arriving Turbo
board and subsystem identity rather than assuming reference power/cooling limits.
[Intel specifications](https://www.intel.com/content/www/us/en/products/sku/245797/intel-arc-pro-b70-graphics/specifications.html).

Reserve proposed public/private ports 11437/11447, subject to a live conflict check.
Before exposing models:

1. Inspect PCI ID, VRAM, driver/firmware, render node and negotiated PCIe link on
   Bigcachy. Check the actual board's power supply and airflow alongside the 5080.
2. Probe llama.cpp SYCL, Vulkan and OpenVINO GenAI compatibility with this exact
   GPU and installed software. Choose the runtime from successful device-specific
   loading and functional checks. No runtime/version is certified in this plan.
3. Pin the chosen build; select the discrete Arc by stable PCI/device identity,
   never a generic `GPU` selector that could capture the existing Intel iGPU.
   Keep current Intel embedding ABI/space and NVIDIA device selection intact.
4. Select models and context/slot/KV geometry from measured available VRAM.
   Do not copy the 5080's 16 GiB or Geekom unified-memory budget onto this card.
5. Provision an independent registry, services, credentials, admission lock and
   durable On/Off control. Test short inference and absent-device startup, then
   publish fixed OpenCode profiles, MCP inventory, operator controls and fleet
   capacity, sync clients and update/ingest Hermes. Benchmarking is a later step.

## Preparation verification

`python -m unittest tests.test_hardware_placements tests.test_presets tests.test_model_tools`
checks shared Radeon geometry, distinct placement IDs, candidate backend rendering,
physical-card exclusivity metadata and exclusion of unprovisioned placements from
the live catalog. These are offline checks, not hardware or deployment certification.
