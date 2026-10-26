# rtx3060ti — RTX 3060 Ti OCuLink vision eGPU on mini-mobile

Local design/vision backend: **Qwen3-VL-8B (Q4_K_M)** in two single-slot 32 k profiles,
served by llama-swap v233 inside the pinned CUDA container on rootless Podman.
Plan + full research history: [`plan.md`](plan.md).

| fact | value |
|---|---|
| card | RTX 3060 Ti 8 GiB (GA104, `10de:2489`), UUID-pinned `GPU-79bf42f9-7cfb-cc1f-d4ad-10ea1918ee52` |
| backend | `ghcr.io/ggml-org/llama.cpp@sha256:490d8cd8…` (CUDA 12.8, b11804) via `runtime.py` (podman store `containers/rtx3060ti`) |
| profiles | `rtx3060ti.describe…` (image ≤ 2048 tok), `rtx3060ti.ocr…` (≤ 8192); mmproj **Q8_0** (the 8 GiB card cannot host the F16 one next to KV+compute) |
| memory rule | `--fit` on (no `-ngl`) + `--fit-target 128`; pinned `-ngl 999` OOMs the mmproj — do not "restore" it from the 5080 config |
| backend port | 127.0.0.1:11448 (key `~/.config/lario-admission/rtx3060ti.backend.key`); authenticated fixed-profile gateway on 11438 |
| boot | `rtx3060ti.service` (user, enabled); ExecCondition = card present by UUID + XFS mounted + no stop marker; absent card ⇒ unit stays dead |
| measured | cold 20.2 s (load+first image), warm ~27 tok/s, 7747/8192 MiB resident, eGPU link 2.5 GT/s ×4 |

## Design workflow (the point of this card)

- **Main model stays the qwen logic model** (`arcB70` now, `geekom7900xt` on l-dev-ai after the
  cutover). Call `lario_images.image_describe` (or select the fixed `rtx3060ti.describe…` profile) for
  anything involving images; switch back for implementation.
- **Seeing bugs:** screenshot (`grim`) → `describe` profile with "act as a UI/UX
  reviewer" — reads layouts, component states, misalignment, contrast, hierarchy.
- **Design systems:** the logic model drafts tokens/specs; the VL model reviews rendered
  screenshots against them; loop.
- **Too big / laptop away:** `image_describe` falls back to the **RTX 5080** vision
  (chain `rtx3060ti → rtx5080`; > ~6 MiB or > 2 images goes straight to the 5080 —
  implemented with fleet registration).

## Ops

```sh
systemctl --user status rtx3060ti            # state
journalctl --user -u rtx3060ti -f            # logs
python3 rtx3060ti/runtime.py check           # presence gate (exit≠0 ⇒ card absent/stopped)
touch /run/user/1000/lario-models/rtx3060ti.disabled && systemctl --user restart rtx3060ti  # stop this boot
rm /run/user/1000/lario-models/rtx3060ti.disabled && systemctl --user restart rtx3060ti     # re-enable
```

Profiles are **generated** from `models.json` (`runtime.py` renders
`config/generated.yaml`); never edit the yaml by hand.

## Traps

- podman containers can outlive the unit and squat the `rtx3060ti-llama` name (run uses
  `--replace`; verify probe uses `-verify` and no port map).
- niri currently drives the display **on this card**; a live eGPU yank is a display event,
  not just a lost backend.
- The card is a "Lite Hash Rate" GA104 — compute-identical, nothing special.
- `--image-min-tokens` warning on load is benign at our 2048/8192 budgets (grounding
  needs ≥1024).

## Repeatable installation and boot recovery

On mini-mobile, with XFS model storage mounted and the pinned container, weights
and llama-swap already staged:

```sh
python3 rtx3060ti/install.py
python3 rtx3060ti/install_clients.py
```

The first command preserves private keys, installs/enables the source backend,
admission gateway and recovery timer, and leaves an active backend running.
`machine-setup/shared/models/install-lifecycle.sh mini-mobile` invokes it too.
The second registers separate inference keys for bigcachy, l-dev-ai and mini-mobile,
checks each authenticated catalog from its client, and renders OpenCode from
machine-setup. Keys remain in private `~/.config/lario-admission` files.
It does not restart OpenCode or change the selected coding model. New config
applies on the next OpenCode start.

The gateway stays available without the card. The backend ExecCondition skips
an absent GPU, unavailable driver, unmounted storage, boot-local stop, or durable
operator Off. Recovery retries enabled hardware every minute, verifies the
registered GPU UUID, and never clears Off or restarts an active service.
Linger is enabled on mini-mobile so user services can start before login.
After reconnecting, serving returns cold; the next eligible request loads its
fixed profile. Firmware/PCIe detection may require a reboot after reconnection.

Verified 2026-10-25: connected GPU and real vision inference; enabled backend,
gateway and timer; repeat installation kept the backend invocation unchanged;
a transient systemd unit with a simulated absent driver skipped ExecStart with
`exec-condition`; tests cover durable Off and reconnect recovery. A physical
unplug/replug and full reboot acceptance test remain pending. Do not unplug
while the card drives a display or serves a request.

## Images MCP: reasonable tasks and routing

`lario_images.image_describe` prefers this card for PNG/JPEG/WebP requests of
one or two images totalling at most 6 MiB. Its two measured 32k profiles cover:

- UI screenshot review: layout, spacing, alignment, colours and component states.
- Reading visible labels or cropped text with `mode: ocr`.
- Simple before/after comparisons and descriptions of ordinary images.

Treat reviews as suggestions; crop or zoom dense text and check exact numbers.
This 8B model is not validated for exhaustive dense documents, tiny text,
complex diagrams, pixel-perfect measurements or reliable complex reasoning.
Larger requests go to the 5080; an unplugged, busy, Off or paused 3060 Ti also
falls back without forcing a profile swap. Results identify the actual device.
Both devices keep the existing admission restrictions.

This setup analyses images. Image generation (including UI mockup images) stays
on the RTX 5080 through the existing separate generation tool.

## OCuLink power guard (mini-mobile)

The 2026-10-26 kernel logged Xid 79 at 07:31 SAST (GPU lost from PCIe),
followed by Xid 154 requesting an OS reboot. PCI enumeration and a previously
loaded model's `/slots` response did not establish that CUDA was usable;
`nvidia-smi` failed with exit 6. Driver failures now report `hardware_unavailable`
rather than a generic reconciling state.

Install the targeted guard with:

```sh
sudo bash rtx3060ti/install-oculink-guard.sh
```

The installer is restricted to mini-mobile with its sole NVIDIA GPU identified
as `10de:2489`. It preserves previous files under `/var/lib/lario-oculink-guard`,
disables NVIDIA runtime D3, installs a boot/device-add/resume guard, and rebuilds
both installed kernels' initramfs images because NVIDIA loads early on this host.
It does not reset a GPU, unload drivers, end the desktop session, or reboot.

The guard discovers the external GPU, its other PCI functions and upstream port
without pinning PCI addresses. It keeps their runtime power control `on` and
sets their exposed per-link ASPM/clock-PM controls to `0` through kernel sysfs.
The internal AMD GPU and unrelated links retain their power settings. An absent
optional eGPU is allowed; ambiguous matching cards are refused. These measures
remove power-transition risks; they cannot repair a loose cable, dock/PSU fault,
or every NVIDIA driver fault. Link speed and global laptop power policy are unchanged.

After reboot, verify:

```sh
python3 rtx3060ti/oculink_guard.py
cat /sys/module/nvidia/parameters/NVreg_DynamicPowerManagement  # expected: 0
nvidia-smi --query-gpu=uuid,name --format=csv,noheader
curl -fsS http://127.0.0.1:11438/health
```

Then run a bounded authenticated inference check and confirm no new Xid 79/154.
The registered UUID is `GPU-79bf42f9-7cfb-cc1f-d4ad-10ea1918ee52`. Keep the
OCuLink enclosure powered and the cable seated while booting. If a normal reboot
does not recover NVML, shut the host down before power-cycling/reseating the eGPU;
never unplug it while it is serving inference or used by the compositor.

References: [NVIDIA runtime D3 settings](https://download.nvidia.com/XFree86/Linux-x86_64/610.43.03/README/dynamicpowermanagement.html),
[NVIDIA Xid catalog](https://docs.nvidia.com/deploy/xid-errors/analyzing-xid-catalog.html).
