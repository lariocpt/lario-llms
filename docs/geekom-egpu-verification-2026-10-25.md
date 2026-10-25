# Geekom eGPU verification, 2026-10-25

Inspected locally on `l-dev-ai`, kernel `6.18.55-2-cachyos-lts`. Configuration
was already installed; no model service was restarted and no generated backend
YAML was edited during this audit.

## Hardware and installed configuration

- PCI `0000:c8:00.0`: AMD `1002:744c`, XFX subsystem `1eae:7905`, bound to
  `amdgpu`. Physical UUID `255c7a14946751e2` matches the owner registry.
- VRAM reported by sysfs: 21,458,059,264 bytes (20,464 MiB).
- The kernel negotiated 16 GT/s PCIe x4 at root port `0000:00:03.1`, the
  M.2 connection. The GPU's internal x16 link is not the host connection width.
  Later idle reads showed 2.5 GT/s x4 at the upstream link; bandwidth under load
  was not measured.
- The boot journal at 21:39:09 SAST reports exactly
  `ROCm0: AMD Radeon RX 7900 XT (20464 MiB, 20428 MiB free)` and llama-swap
  listening inside the rootless container.
- The installed `geekom7900xt.service` matches the source unit. Backend and
  admission gateway have enablement links in `default.target.wants`.
- The backend checks manual stop intent and the physical device before
  `ExecStartPre` generates configuration. An unavailable card exits the
  `ExecCondition` with status 1 and skips startup. The runtime checks identity
  again before the ROCm probe and Podman execution.
- `machine-setup --machine l-dev-ai --agents` reports the live OpenCode file
  already up to date. Its Radeon endpoint is localhost port 11436 with three
  immutable profiles and a private client credential. Geekom remains the
  default. No retired Radeon provider is present in the live provider map.
  Retained private credentials were not deleted or copied into source.

## Concerns and verification limits

The existing `~/card-watch/edges.log` recorded four transient changes from PCI
vendor ID `1002` to `ffff` and back between 21:39:08 and 21:39:19 SAST on this
boot. This is evidence of intermittent configuration-space reads, not proof of
a particular power, cable, firmware or driver cause. The kernel also logged
`Failed to enable gfxoff!`, a MES response failure and a register-wait failure.
Successful enumeration alone does not establish stable inference.

Admission initially failed to bind its Tailscale address and was restarted by
systemd five seconds later. The journal records the restart; this audit could
not confirm subsequent HTTP health.

The initial execution environment projected the model XFS mount read-only, hid
`/dev/kfd` and `/dev/dri`, and denied systemd bus access and connections to
the local HTTP endpoint. Those restrictions did not show that the host's model
filesystem was actually read-only or that its device nodes were absent.

## Live follow-up after host access was enabled

Authenticated model discovery and rendered OpenCode credentials passed on
mini-mobile, Bigcachy and Geekom for both `geekom` and `geekom7900xt`.
The laptop had stale private client credentials; installation of its existing
registered keys and `opencode reload` repaired access. The user confirmed that
the credential error disappeared. OpenCode was reloaded on all three hosts.
No model service was restarted.

The Radeon runtime guard resolves the live physical card at
`0000:c8:00.0`, `/dev/dri/renderD128`, with the registered UUID. systemd unit
verification passed. Both backend services and both gateways are active with
zero backend restarts this boot. Radeon loaded the Qwen 131072-token profile,
reported ready, and logged an HTTP 200 chat completion at 21:51:37 SAST.

Strix Halo reports the shared Q4 Qwen backend ready, with active requests,
spare stream slots and no gateway error. Slot counters show ongoing token
generation while other requests process long prompts. The independent short
completion probe was still waiting behind that work at the time of this
record; a busy pool does not imply a credential failure. The repair helper now
allows a probe to share its resident pool when capacity remains, while refusing
to swap a busy exclusive model.

Sustained Radeon stability and a physical dock-absent boot remain untested.

## Validation

39 focused LLM tests passed across model lifecycle, device health, backend
recovery, startup profiles, client repair, operator panel and hardware placements.
Three JavaScript panel capacity tests also passed. Regression coverage includes rejection of a
stale PCI identity after card loss, missing KFD, and refusal to probe or launch
Podman when the registered GPU is unavailable. The unit ordering check protects
the condition before configuration and execution.

All 25 machine-setup tests passed, including rendering all three development
client overlays while preserving unrelated providers, plugins and private
settings. The l-dev-ai full setup dry-run passed. Python compilation and git
diff whitespace checks passed. The generated guide, MCP and control HTML pages
were rebuilt and checked against their Markdown sources using the existing
2026-10-23 benchmark report; no new benchmark measurements were invented.

## Remaining acceptance

1. From an unrestricted host shell, inspect current GPU health and obtain an
   authenticated completion through port 11436, then exercise sustained GPU
   inference while monitoring kernel and card-watch logs.
2. Investigate any repeated identity-read or MES failures before recording the
   dock as stable. Avoid choosing driver or firmware changes without that
   evidence.
3. Shut down before disconnecting the M.2 dock; boot with it absent and confirm
   the backend is skipped without a failed/restarting service or model process.
   Confirm the integrated Geekom provider remains usable.
4. Shut down, reconnect the dock and verify normal boot and inference recovery.
