# rtx3060ti — RTX 3060 Ti eGPU on mini-mobile: plan (pick-up point)

Status: **P0 + P1 DONE on 2026-10-24 — service live on this laptop.** Implemented as
**podman CUDA** (option B), not native: no sudo for the CUDA toolkit, ghcr CUDA image
(sha `490d8cd8…`) covers sm_86, host `libcuda.so.1` binded — verified end-to-end with a
real screenshot (cold 20.2 s, warm ~27 tok/s, 7747 MiB). Two deviations from §3.2/§3.3
forced by the 8 GiB card: mmproj **Q8_0** (F16 OOMs next to KV+compute) and **`--fit`
auto with `--fit-target 128`** instead of pinned `-ngl 999`. Unit enabled
(absent-card-safe); a real reboot test is still owed (§7.3). Remaining: **P2 fleet
registration** (catalog/boot_ready/model_tools/placements/opencode×6/admission clients/
image_describe fallback chain/observability), then **P3 validation**, then P4
(7900xt→l-dev-ai — blocked on the user's ATX PS_ON hairpin; card confirmed absent from
l-dev-ai PCI tree on 2026-10-24). See `rtx3060ti/README.md` for daily ops + workflow.

Original plan (pre-implementation): Written 2026-10-23 on cachyos-mini-mobile while
bigcachy is being physically moved (SSH to bigcachy is down right now — do not depend on it).
Everything below was verified on this box unless marked "on bigcachy" or "in-flight".

## 1. The ask (user intent, verbatim)

- The **GeForce RTX 3060 Ti** is the newly plugged-in OCuLink eGPU on this laptop (it is an
  **NVIDIA** card, not a Radeon — the Radeon on this box is the HawkPoint1 iGPU, which stays
  out of inference).
- llama.cpp for it must **auto-start at Linux boot, only when the card is plugged in**
  (absent-card boots skip inference, same as the 7900xt pattern).
- Use it for **visual design work**: seeing bugs (screenshots), making design systems,
  making designs → needs **image upload / vision support**.
- It must **work together with a qwen logic model** (user: "better intel b70 qwen or 7900xt
  qwen") for design + design implementation.
- **Any computer on the network can use it for design** (fleet-wide access, not just this
  laptop).
- **Fallback:** if an image is too big for the 3060 Ti, or mini-mobile/rtx3060ti is
  offline → the 5080 vision (bigcachy) takes the request.
- Then update: the appropriate **MCPs**, the **guidelines**, the **models web + logging
  pages**, and **all opencode configs in machine-setup**.

## 2. Research findings (all verified 2026-10-23 unless noted)

### 2.1 The eGPU itself (this box, cachyos-mini-mobile)

| fact | value |
|---|---|
| card | NVIDIA GeForce RTX 3060 Ti "Lite Hash Rate" (GA104, 8 GiB GDDR6) |
| PCI | `0000:01:00.0` (OCuLink eGPU slot) |
| driver | NVIDIA-SMI 615.78.08, CUDA UMD 13.4 |
| display | niri currently drives the display on this GPU (process visible in nvidia-smi) |
| idle | P8, 7 W, 34 °C |
| PCIe link (idle) | **2.5 GT/s × 4** (PCIe 2.0 x4 ≈ 1 GiB/s effective). Re-measure under load — matters for model load time, barely for token generation (weights sit in VRAM). If it stays 2.0 x4 under load, budget slow first-load and note it in MACHINE.md |
| compute arch | GA104 = **sm_86** (Ampere). NOT covered by the existing cuda build flag (`CMAKE_CUDA_ARCHITECTURES=120`, 5080-only) in `scripts/build_llama_release.py` |

Box facts: Ryzen 7 8840U, 26 GiB RAM; `/mnt/xfs` 240 GiB free; podman 6.1.4 (rootless,
7900xt storage root exists at `/mnt/xfs/AI_Models/containers/7900xt`); docker CLI present;
**no nvidia-container-toolkit**; host `llama-swap` v233 (2026-06-29) at
`/mnt/xfs/AI_Models/bin/llama-swap` (proxy — backend-agnostic, it execs `llama-server`).
GGUF store has only `muse-glimmer/` and `qwen3.8/` — **no VL weights yet on this box**.
`7900xt.service` + `lario-admission@7900xt` are still enabled but dead (card absent →
`ExecCondition` fails; leave enabled until the cutover removes them properly).

### 2.2 Reference implementation to copy: `rtx5080/` (bigcachy, native CUDA)

- `rtx5080/models.json`: profiles `ocr` (qwen3-VL, 32 k, s1, KV q8_0, `--image-max-tokens 8192`)
  and `describe` (qwen3-VL, 64 k, s1, KV q8_0, `--image-max-tokens 2048`) both on
  `Qwen3-VL-8B-Instruct-Q4_K_M.gguf` + `mmproj-F16.gguf`, plus a text `qwen3.8` profile.
  Weights at `/mnt/xfs/AI_Models/gguf/qwen3-vl/`.
- `rtx5080/systemd/rtx5080.service`: **native** — `ExecStart=%h/.local/bin/llama-swap
  -config rtx5080/config/generated.yaml -listen :11435`, `ExecStartPost … warm`,
  `TimeoutStartSec=1860`, `WantedBy=default.target`.
- Vision config lore (`llama-cpp/vision-config.yaml`): `--mmproj` is fetched automatically
  with the `-hf` repo (without it the model loads but silently ignores images); KV for 8B
  at 32 k ≈ 1 GiB (q8_0); never point an agent `default:` at a side-task vision model.
- VRAM math for 8 GiB: Q4_K_M 8B ≈ 5.15 GiB + mmproj F16 ≈ 0.6 GiB + KV 32 k q8_0 ≈ 1 GiB
  + compute ≈ 0.5 GiB → **≈ 7.3–7.5 GiB: one slot fits, two do not**. 64 k context (2 GiB
  KV) is borderline — start 32 k, grow after measurement.

### 2.3 eGPU auto-start pattern to copy: `7900xt/` (this box, absent-card safe)

- `7900xt/models.json` is the device registry: `.host`, `.service`, `.engine=podman`,
  `.image` (pinned `ghcr.io/ggml-org/llama.cpp` sha256), `.device_identity`
  (`device_id 0x744c`, `unique_id 255c7a14946751e2`, `minimum_vram_bytes`), `.port=11436`,
  `.backend_port=11446`, `.config`, `.container`, model args, `.presets` with validation.
- `7900xt/runtime.py`: `check` / `run`; refuses on stop marker (`shared/lifecycle.py`),
  unmounted `/mnt/xfs`, or **device identity mismatch** (`shared/gpu.py:radeon_device` —
  "never assume a PCI address or iGPU fallback"); verifies physical card via
  `--list-devices` before starting, fails closed.
- `7900xt/systemd/7900xt.service` + drop-ins: `ExecCondition=…boot_ready.py 7900xt`,
  `EnvironmentFile=%h/.config/lario-admission/7900xt.env`,
  `ExecStartPre=…shared/serving/configure.py 7900xt`, `TimeoutStartSec=1860`,
  `Restart=on-failure`. **This is the exact shape a `rtx3060ti.service` should take**,
  with an NVIDIA `check` (nvidia-smi presence + PCI id `10de:2489` + 8 GiB, instead of
  the ROCm UUID probe).
- Admission gateway: templated `lario-admission@.service` (`%i.env` in
  `~/.config/lario-admission/`) fronts the backend on the public port with per-client keys.
  A `lario-admission@rtx3060ti` instance is the standard companion (7900xt has one).

### 2.4 Logic-model side (the "qwen" partner) — no new build needed

- **arcB70** (bigcachy, live): 32 GiB Arc, SYCL, port **11437**. Active profile after the
  in-flight revert: `arcB70.qwen3.8-smart-q4-128k.c131072.kq4_0-vq4_0.s5.prepared.1d37ed04a2`
  (this session runs it). Reachable from mini-mobile via tailnet `100.127.91.5:11437` —
  already in mini-mobile's live opencode config.
- **7900xt** (cutover in flight): the RX 7900 XT moves from this laptop to **l-dev-ai as an
  eGPU** (in-flight placement: host l-dev-ai, "external GPU via spare M.2 NVMe slot
  adapter", `exclusive_with winmax7900xt`). User decision: **after cutover, remove the
  `winmax7900xt` and `gkm7900xt` aliases** — the 7900 XT then exists once, on l-dev-ai.
  Open: does the existing `7900xt` alias re-point to l-dev-ai (its owner moves) or does
  the card get a new alias? `7900xt` is still referenced everywhere (MCP tuple, endpoints
  maps, opencode providers) — re-pointing the owner is the least-churn option.

### 2.5 bigcachy has UNCOMMITTED work (box is being moved — do not commit/push it)

`git status` on bigcachy (captured 2026-10-23 ~20:00, before it went dark):
`M arcB70/README.md, M arcB70/models.json, M arcB70/opencode.prepared.json,
M media/PLAN.md, M rtx5080/encoder/{runner,test_fidelity,test_gates}.sh,
M shared/serving/web/placements.json, ?? docs/crypto-plan/`.
The arcB70/placement diffs are the 256k/2s experimental → 128k/5s active-profile revert
(matches live state). The media/encoder diffs are the Inception damaged-source fidelity
gate work. `docs/crypto-plan/` is untracked (wallet/dashboard planning). **Our rtx3060ti
work must land as its own commit containing only rtx3060ti + fleet-wide registration
files, and must not sweep in these paths.**

### 2.6 Integration inventory (where a new hardware alias touches things)

lario-llms:
- new `rtx3060ti/` service dir: `models.json`, `config/` (llama-swap yaml), `systemd/`
  (+drop-ins), `runtime.py` only if podman is chosen (native → no runtime.py)
- `shared/serving/catalog.py`: `HARDWARE=('geekom','7900xt','rtx5080')`,
  `OWNER_HARDWARE=(*HARDWARE,'arcB70')` → add `rtx3060ti` (owner extension, arcB70-style)
- `shared/serving/web/placements.json` (+ regenerate via `python -m shared.placements`)
  → **models web page** (`models.in.drlario.org`)
- `shared/model_tools/export_choices.py` → `machine-setup/shared/agents/model_choices.json`
  (schema_version 2; do not hand-edit)
- `scripts/build_llama_release.py`: cuda backend hard-codes `CMAKE_CUDA_ARCHITECTURES=120`
  → needs a per-hardware arch (86 for GA104) **only if we go native-build**
- observability (the **logging page** `models.logs.in.drlario.org` → Grafana ← Loki ←
  Alloy): `observability/config.alloy.template` (unit→hardware relabels),
  `observability/exporter.py` (NVIDIA query already supported), `observability/install.py`
  (unit allowlist), `observability/README.md` owners table
- docs: `MCP_USAGE_GUIDE.md`, `docs/guide.md`, `README.md`

machine-setup ("all the opencode repos"):
- `shared/agents/model_tools.py`: `HARDWARE=('geekom','7900xt','rtx5080','arcB70')`
  (**lario_models MCP**) + choices-snapshot validation
- `shared/agents/image_tools.py` (**lario_images MCP**): `image_describe` hard-wires the
  rtx5080 owner + `rtx5080.<mode>.` profile prefix + `clients.json['rtx5080']` key +
  fixed base URLs (owner-local vs tailnet 100.127.91.5) → **rework to the
  rtx3060ti→rtx5080 fallback chain** (§3.6); `image_generate` stays rtx5080-only
  (bigcachy card)
- `shared/admission/{provision,install_client}.py` — client-key flow for the new owner;
  `machine-setup/shared/models/install-lifecycle.sh` — owner mapping + CLI links
- `machines/{bigcachy,l-dev-ai,mini-mobile,surveillance,lario-windows,i-endeavour}/config/
  opencode.jsonc` + `shared/agents/opencode.prepared.json` / `opencode_fixed_models.json` /
  `opencode_profile_models.json` (provider blocks + `LARIO_MODELS_ENDPOINTS` maps)
- `machines/mini-mobile/{MACHINE.md,machine.conf,steps/30-model-runtime.sh,
  steps/45-agent-configs.sh,steps/52-model-lifecycle.sh,steps/80-verify.sh}`
- `lib/fleet.sh` (endpoint markers, e.g. `@7900XT_ENDPOINT@`, `@ARCB70_ENDPOINT@` — add
  `@RTX3060TI_ENDPOINT@` style marker for non-owner machines)
- rendered live: `~/.config/opencode/opencode.jsonc` on each box via
  `./setup.sh --agents` (cmp-guarded renderer, backs up live files)

### 2.7 Port inventory (pick clean numbers)

| port | use |
|---|---|
| 11434 | geekom (l-dev-ai) |
| 11435 | rtx5080 (bigcachy, loopback) |
| 11436 | 7900xt (mini-mobile now → l-dev-ai after cutover) |
| 11437 | arcB70 (bigcachy) |
| **11438** | **rtx3060ti public (proposed, mini-mobile; LAN + tailnet-reachable for all fleet clients, §3.5)** |
| 11445/11446/11447 | rtx5080 / 7900xt / arcB70 backends |
| **11448** | **rtx3060ti backend (proposed)** |

(11434 on bigcachy is the model-less ollama squatter — never used; unrelated.)

## 3. Proposed design

1. **Alias `rtx3060ti`, owner `mini-mobile`** (rename to plain `3060ti` is a one-line
   change in each §2.6 location if the user prefers; `rtx5080` precedent argues for the
   prefix).
2. **Runtime: native CUDA** (copy the rtx5080 shape: `llama-swap` + generated config +
   systemd user unit). Reason: no nvidia-container-toolkit here; rootless podman + NVIDIA
   needs manual `/dev/nvidia*` passthrough the ROCm pattern doesn't need. **Option B**
   (podman `ghcr.io/ggml-org/llama.cpp:<pinned>-cuda` with `--device /dev/nvidia0..` +
   `--group-add keep-groups`) stays open if a container is wanted for fleet symmetry.
   Needs a CUDA **sm_86** `llama-server`: either extend `build_llama_release.py`
   (`--arch` per hardware) or reuse an existing sm_86-capable build — **check the build
   receipt of the v233 toolchain first** (it may already be multi-arch).
3. **Models (start minimal, one slot each):**
   - `design`: Qwen3-VL-8B-Instruct-Q4_K_M + mmproj-F16, 32 k, KV q8_0, `--parallel 1`,
     `--image-max-tokens 8192` (design-system critique, bug-seeing, layout analysis)
   - `ocr`: same weights, 32 k, KV q8_0, `--image-max-tokens 2048` (fast text/compare)
   - Same weight files as the 5080 (`gguf/qwen3-vl/`) → download once onto this box's XFS.
   - Deferred: a Qwen3-VL-4B long-context/second-slot profile if 8 GiB leaves room
     (measure first).
4. **Auto-start (absent-card safe):** `rtx3060ti.service` mirroring `7900xt.service`:
   `ExecCondition` = card present (nvidia-smi + PCI id `10de:2489` + ≥8 GiB) AND
   `boot_ready.py rtx3060ti` AND no stop marker; `EnvironmentFile` from
   `~/.config/lario-admission/rtx3060ti.env`; `ExecStartPre shared/serving/configure.py
   rtx3060ti`; `WantedBy=default.target`; linger already enabled. Plus
   `lario-admission@rtx3060ti` gateway on 11438. Card absent → unit stays dead, nothing
   else on the laptop is affected.
5. **Fleet-wide access (user: "any computer on the network should be able to use this
   for design"):**
   - The `rtx3060ti` admission gateway binds the public port for LAN+tailnet (owner
     pattern: llama-swap listens `:11438`; tailscale covers remote, docked LAN IP
     192.168.10.243 is the home fallback). **Canonical endpoint for other machines is the
     tailnet IP** (fleet convention — see mini-mobile's own config using `100.127.91.5:…`
     for bigcachy owners): `http://<mini-mobile tailnet IP>:11438/v1`. Re-verify the
     tailnet IP at implementation (MACHINE.md warns tailscale IPs change on re-login;
     the 100.103.22.121 registry value is as-of 2026-09-13).
   - **Every machine's opencode config gets the `rtx3060ti` provider** (all six in
     machine-setup) with the image-modal VL profiles; owner mini-mobile uses
     `127.0.0.1:11438`, all others the tailnet endpoint via a new `@RTX3060TI_ENDPOINT@`
     marker in `lib/fleet.sh`.
   - **Per-client keys:** `shared/admission/provision.py` on mini-mobile (owner) +
     `install_client.py` on each client → `~/.config/lario-admission/clients.json`
     gains an `rtx3060ti` entry on every box (same mechanism as the existing
     `rtx5080`/`7900xt`/`arcB70` entries). `machine-setup/shared/models/
     install-lifecycle.sh` owner `case` maps mini-mobile's owner hardware 7900xt →
     rtx3060ti (after the 7900 XT leaves) and adds the `rtx3060ti` CLI link.
   - Roaming caveat (document in guidelines): when the laptop is off the tailnet,
     `rtx3060ti` is simply offline → fallback (§3.6) covers it; docked-LAN clients can
     also use the LAN IP.
6. **image_describe fallback chain (user: "if images too big or it's offline → 5080"):**
   Rework `machine-setup/shared/agents/image_tools.py` (the `lario_images` MCP):
   - Generalize the hardwired rtx5080 path: vision target chain
     **`rtx3060ti` → `rtx5080`**, each resolved to `{base, key, profile-prefix}` from
     `clients.json[<hw>].apiKey` + endpoints (owner-local `127.0.0.1` when
     `socket.gethostname()` matches the owner, else the owner's reachable IP).
   - **Pre-check "too big" for the 3060 Ti** (deterministic, before any network call):
     the 8 GiB card's budget is the `--image-max-tokens` of its profile (design 8192 /
     ocr 2048) plus 1 slot. Rule of thumb to tune at bring-up: total bytes ≤ ~6 MiB and
     ≤ 2 images → try rtx3060ti; anything above → straight to rtx5080 (its 16 GiB and
     20 MiB/4-image tool budget stay the ceiling).
   - **Reactive fallback:** probe primary first (`/v1/models`, ~8 s). Offline (timeout /
     connection refused — laptop asleep/absent card) or runtime 413/422/429/503 →
     retry the same request on rtx5080 once. Result already reports `owner` + `model`,
     so the caller sees which card answered. Both Off/paused → error with the existing
     operator-page hint; never force a swap.
   - `image_generate` stays rtx5080-only (generation is the 5080's job; 8 GiB is for
     vision). Tool description updated to document the chain.
7. **Design workflow (how the user actually uses it):**
   - The `rtx3060ti` provider lands in opencode with **`"input": ["text","image"]`
     modalities** on the VL profiles → image uploads/attachments work directly in chat
     (same shape as `rtx5080.ocr`/`rtx5080.describe`), on every machine.
   - Main conversation model stays the **qwen logic model** (`arcB70` now; `7900xt` after
     the l-dev-ai cutover). The user switches to a `rtx3060ti` model (or the agent calls
     `image_describe`, which auto-falls-back per §3.6) for image-heavy passes, then back
     for implementation.
   - Guidelines (MCP_USAGE_GUIDE.md + a short `rtx3060ti/README.md`): "screenshot →
     rtx3060ti for bug/design reading → logic model for the fix"; "design system =
     logic model writes tokens/specs, rtx3060ti reviews rendered shots"; "big/many
     images or laptop away → 5080 via the same tool".
8. **7900xt cutover is separate work** (l-dev-ai eGPU, owner re-point, then delete
   `winmax7900xt` + `gkm7900xt` aliases per user). Sequence it AFTER bigcachy is back and
   its uncommitted work is settled; this plan only keeps the alias question open (§2.4).

## 4. Open questions (defaults in bold)

1. **Podman or native?** **→ native** (no nvidia-container-toolkit; rtx5080 precedent).
2. **Alias name?** **→ `rtx3060ti`** (rtx5080 precedent).
3. **Vision model mix?** **→ Qwen3-VL-8B Q4_K_M, two 32 k one-slot profiles** (same
   weights as 5080). 4B/64 k only if VRAM headroom proves out.
4. **Does `7900xt` re-point to l-dev-ai after cutover, or new alias?** **→ re-point
   (owner move, no churn)** — confirm with user.
5. **`image_describe` routing — DECIDED (user):** rtx3060ti primary on the chain,
   rtx5080 fallback when the image is too big or rtx3060ti is offline (§3.6). Tunables:
   the byte/count pre-check thresholds (start ~6 MiB / 2 images) and the probe timeout.
6. **PCIe 2.0 x4 under load:** re-measure during first live use; if confirmed, document
   expected load times in MACHINE.md.
7. **bigcachy move:** when is it back? The models-web/placements + fleet push want
   bigcachy's uncommitted arcB70/placement state settled first (our commit must not
   include those paths).

## 5. Implementation phases (order matters)

- **P0 — bring-up on this box (no fleet changes):**
  1. Download `Qwen3-VL-8B-Instruct-Q4_K_M.gguf` + `mmproj-F16.gguf` →
     `/mnt/xfs/AI_Models/gguf/qwen3-vl/` (mirror the 5080's exact files).
  2. Obtain sm_86 CUDA `llama-server` (check v233 receipt first; else
     `build_llama_release.py --backend cuda` with arch 86) into
     `/mnt/xfs/AI_Models/bin` alongside llama-swap.
  3. Hand-test: raw `llama-server` with the `design` args → load, VRAM, one image
     completion, tokens/s, and re-read PCIe link under load.
- **P1 — service + auto-start (this box):**
  `rtx3060ti/models.json` (device identity `10de:2489`, min 8 GiB, port 11438/11448),
  `config/` yaml, `systemd/rtx3060ti.service` + drop-ins + NVIDIA check in a
  `runtime.py`-equivalent (or extend `shared/gpu.py` with `nvidia_device()`),
  admission instance, enable units. Verify: boot with card → up; pull card, boot →
  dead; stop-marker honored; operator page can switch profiles.
- **P2 — fleet registration (repos, one clean commit):**
  catalog.py + placements.json (+`python -m shared.placements`), export_choices →
  model_choices.json, machine-setup `model_tools.py` HARDWARE + endpoints maps,
  **`image_tools.py` fallback chain (§3.6)**, all six `machines/*/config/opencode.jsonc`
  (+ `@RTX3060TI_ENDPOINT@` marker in `lib/fleet.sh`), admission client keys to every
  machine (`provision.py` on owner → `install_client.py` per client),
  `install-lifecycle.sh` owner map, observability relabels/allowlist/README, docs
  (MCP_USAGE_GUIDE, guide, per-machine MACHINE.md). Render on each box:
  `./setup.sh --agents` (mini-mobile first).
- **P3 — validation + write-up:**
  image-upload chat test with a screenshot (bug-seeing), a design-system pass, one
  logic-model implementation round; `image_describe` from **at least two non-owner
  machines** via tailnet; **exercise both fallback paths** (oversized image → 5080
  directly; laptop asleep → probe timeout → 5080) and confirm the result reports the
  answering owner/model; Grafana dashboard shows `hardware=rtx3060ti` streams;
  models.in.drlario.org card renders with the right owner.
- **P4 — (separate) 7900xt cutover to l-dev-ai**, then retire `winmax7900xt` /
  `gkm7900xt` per user; re-point `7900xt` owner if §4.4 confirmed.

## 6. Risks / traps

- **bigcachy is being moved**: its uncommitted tree (§2.5) is the only copy of the arcB70
  revert + media gate work + crypto-plan docs. Do not push, pull-merge, or render from
  it until it's back and settled. This plan + the diffs captured above are the snapshot.
- **8 GiB is tight**: two slots or a 64 k profile will OOM/swap. Start 32 k/s1, measure
  with `nvidia-smi`, then grow. `--cache-ram 0` (all KV on GPU) like the 5080.
- **PCIe 2.0 x4** (if confirmed under load): slow cold loads (~minutes for 5 GiB at
  ~1 GiB/s) — expected, document it; inference itself is VRAM-bound, not link-bound.
- **sm_86**: the pinned cuda build is arch 120-only — using it on the 3060 Ti will fail
  at load time, not at build time.
- **Dual-boot laptop**: never touch the NTFS partitions (MACHINE.md); XFS model store
  only.
- **Display GPU**: niri currently runs on the eGPU; an eGPU power-loss while booted is
  a display event, not just a missing unit. The unit's absent-card behavior only covers
  *boot*; hot-unplug behavior is out of scope for now (note it, don't solve it).
- **Do not** point the laptop's opencode `default:` model at the vision profiles
  (vision-config lore); they are side-task models.
- mesh-repo-sync after any push: fast-forward the other boxes; a moving/absent bigcachy
  will be "blocked, untouched" — expected.

## 7. Pick-up checklist (cold start)

1. This file, §2 facts, §3 design, §4 defaults.
2. Verify bigcachy is back: `ssh bigcachy git -C ~/Projects/personal/lario-llms status` —
   expect the §2.5 tree; settle it before P2.
3. Verify eGPU still present: `nvidia-smi -L`; `cat /sys/bus/pci/devices/0000:01:00.0/current_link_speed`.
4. Confirm §4.4 (7900xt re-point) with the user (§4.5 routing is decided: 3060ti → 5080).
5. Re-verify mini-mobile's **current tailnet IP** (`tailscale ip -4`) before writing any
   endpoint into client configs; also note its docked LAN IP for the LAN-only case.
6. Start P0 step 1 (weights download).
