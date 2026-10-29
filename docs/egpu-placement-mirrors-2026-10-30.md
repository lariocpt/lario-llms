# Swappable RX 7900 XT and RTX 3060 Ti — 2026-10-30

Four placements are configured with the same original weights, model args,
contexts, slots, KV precision and pinned container images:

| Display prefix | Host | Hardware/provider ID | Models |
|---|---|---|---|
| gkm 7900xt | l-dev-ai | geekom7900xt (existing routes preserved) | Muse Glimmer, DFlash, Qwen3.8 |
| gdp 7900xt | cachyos-mini-mobile (GPD Win Max) | gdp7900xt | exact Radeon mirror |
| gdp 3060ti | cachyos-mini-mobile | rtx3060ti (existing routes preserved) | Qwen3-VL-8B describe/OCR, Q4 weights, Q8 KV/projector, 32K |
| gkm 3060ti | l-dev-ai | gkm3060ti | exact vision mirror |

These are placements of the same registered physical cards, not permission to
use a same-model replacement or an internal GPU. Radeon unique ID and NVIDIA
UUID/VRAM checks are resolved on each start. No PCI bus address/index is fixed.
New model stores are on XFS (`/mnt/AI_Models` or `/mnt/xfs/AI_Models`); app/source
files stay in this checkout. Existing placements retain their original runtime
and IDs, so returning either card to its previous machine works.

## Activation and recovery

`shared/egpu.py` owns the optional mirrored runtime and the private Podman
command. Both mirrors have separate containers/stores, public/loopback ports,
credentials and systemd units. `shared/install_egpu.py HARDWARE` installs them
idempotently without restarting active inference. Backend ExecCondition checks
host, XFS, durable Off/manual stop and registered GPU availability. The recovery
timer retries enabled hardware each minute without clearing operator intent.
A container-side device probe must also see exactly the intended CUDA/ROCm card;
CPU/internal-GPU fallback is refused. No container is pulled at inference time.

Authenticated gateways remain reachable with a card absent and refuse serving
with hardware_unavailable. Registered client credentials were verified from all
three development machines before config publication. Off/on remains in the
operator interface; disconnect/reconnect may require an ordinary host reboot.
No reboot, GPU reset, driver unload or model interruption was performed here.

The Geekom's CUDA image and vision weights have been staged. Radeon model
files already exist on mini-mobile. The laptop was rebooted with the registered RX 7900 XT attached; identity
and driver detection passed. Its interrupted ROCm image download is being
recovered from the Geekom cache before a bounded inference check. Geekom
3060 Ti inference remains pending its driver installation and connected card.

The Geekom has no NVIDIA driver packages and remote sudo requires a password.
The exact reviewable root prerequisite is machine-setup's
`machines/l-dev-ai/steps/32-egpu-runtime.sh`; render it to `out/egpu-runtime-l-dev-ai.sh`
and run it locally with sudo when convenient. It installs the DKMS driver and
utils against existing kernel headers, stages runtime-D3-off/UVM settings and
fleet firewall access. It does not reboot or replace the working AMD stack.
See `machine-setup/docs/EGPU-SWAP-2026-10-30.md` for commands and acceptance steps.

## OpenCode and images

All three source overlays, shared public catalogs and live settings expose the
four prefixes. The Geekom 256K Flash Next default remains unchanged. New
credentials are private and never committed. Current OpenCode instances are not
force-reloaded; reopen an idle client for new providers/tool schemas.

The canonical images MCP tries the local 3060 Ti placement first, then the
other placement, then RTX 5080, within the existing two-image/6 MiB limits.
Larger image analysis and image generation retain the existing 5080 path.
The logical `gdp3060ti` result maps to compatible `rtx3060ti.*` profile IDs.
Model-options MCP includes both new placement catalogs and absent-GPU state.

Validation covers model/preset parity, UUID/store/host isolation, absent-GPU
refusal, original profile ID stability, TI-to-TI-to-5080 failover, and all three
provisioning dry runs. The MCP suite retains the existing image-upscale tools.
