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
| backend port | 127.0.0.1:11448 (key `~/.config/lario-admission/rtx3060ti.backend.key`); public 11438 arrives with the admission gateway (fleet registration) |
| boot | `rtx3060ti.service` (user, enabled); ExecCondition = card present by UUID + XFS mounted + no stop marker; absent card ⇒ unit stays dead |
| measured | cold 20.2 s (load+first image), warm ~27 tok/s, 7747/8192 MiB resident, eGPU link 2.5 GT/s ×4 |

## Design workflow (the point of this card)

- **Main model stays the qwen logic model** (`arcB70` now, `7900xt` on l-dev-ai after the
  cutover). Switch to `rtx3060ti.describe` (or call `lario_images.image_describe`) for
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
