# GPU software upgrades and relocation preparation — 2026-10-23

These changes cover l-dev-ai and Bigcachy. Arc B70 is not installed and the
Radeon has not moved to Geekom. Short functionality checks replace benchmarking
for this iteration. Source pins are in `shared/runtime-versions.json`; recorded
checks are in `research/software/20261023-runtime-checks.json`.

## Decisions from the live inventory

| Component | Observed baseline | Upgrade decision |
| --- | --- | --- |
| Geekom llama.cpp Vulkan | build 11389, 16c163d56, October 4 | Pinned v0.7.0 activated after explicit restart approval; short checks passed |
| RTX llama.cpp CUDA | build 11392, 46847e615, October 4 | Pinned v0.7.0 for SM120 with GCC15 activated during idle maintenance |
| Arc candidate backend | Not installed | Current Vulkan build prepared; SYCL remains an optional later comparison |
| Geekom Mesa/RADV | 26.2.4 | Already current in configured distro repositories at inspection |
| Geekom system ROCm | 7.2.4 | Retain system packages; install isolated ROCm 10.1/PyTorch for gfx1151 and gfx1100 |
| Bigcachy CUDA PyTorch | 2.14.1+cu130, CUDA works | Already current stable; preserve image-generation environment |
| Intel XPU PyTorch | Separate environment absent | Install 2.14.1+xpu separately; verify existing iGPU; B70 unverified |
| Intel compute-runtime | 26.35.39758.10 | Matches latest upstream release inspected; retain |
| OpenVINO Python stack | Runtime 2026.4.0, GenAI/Tokenizers 2026.4.0.0 | Upgrade all three together to 2026.4.1 / 2026.4.1.0 |
| Bigcachy kernel/NVIDIA/CUDA packages | Running NVIDIA 615.71.09; distro updates available | Full system update requires interactive sudo and a coordinated reboot |

## Why these versions

The official llama.cpp v0.7.0 release resolves to commit
`620d2225cc436ab0b001e3200e590e3b286ef9ab`. It includes explicit Vulkan shader
counts for Arc Pro B65/B70, multi-device Vulkan host-memory handling and a
CUDA/HIP flash-attention race fix. These are compatibility/correctness reasons
to prepare it; release notes do not prove better speed on this fleet.
[Upstream release](https://github.com/ggml-org/llama.cpp/releases/tag/v0.7.0).

AMD's current compatibility documentation covers gfx1151 Ryzen APUs and gfx1100
Radeon hardware. The stable AMD wheel index resolves PyTorch
`2.14.0+rocm10.1.0` with both `device-gfx1151` and `device-gfx1100` extras. It did
not offer a 2.14.1 ROCm wheel at inspection, although generic/CUDA/XPU PyTorch
2.14.1 is available. The bundled SDK avoids mixing vendor Ubuntu packages into
CachyOS's system ROCm. CachyOS itself is not an AMD-supported distro claim.
[AMD matrix](https://rocm.docs.amd.com/en/latest/compatibility/compatibility-matrix.html),
[AMD PyTorch install](https://rocm.docs.amd.com/projects/ai-ecosystem/en/latest/frameworks/pytorch/install.html),
[TheRock packaging](https://github.com/ROCm/TheRock/blob/main/RELEASES.md).

The isolated Intel environment uses official XPU wheels. Bigcachy's existing
CUDA image environment remains separate and already runs the latest stable
PyTorch patch inspected. The Intel compute-runtime release matches the installed
version. Installing a wheel does not certify the incoming Arc board.
[PyTorch stable](https://github.com/pytorch/pytorch/releases/tag/v2.14.1),
[Intel GPU support](https://docs.pytorch.org/docs/2.14/notes/get_start_xpu.html),
[Intel runtime](https://github.com/intel/compute-runtime/releases/tag/26.35.39758.10).

OpenVINO's patch fixes GPU and model correctness issues. Runtime, GenAI and
Tokenizers are upgraded as a matched set, rather than replacing Runtime alone
and reproducing the earlier shared-library ABI mismatch.
[Runtime patch](https://github.com/openvinotoolkit/openvino/releases/tag/2026.4.1),
[GenAI patch](https://github.com/openvinotoolkit/openvino.genai/releases/tag/2026.4.1.0).

## Reproducible preparation and rollback

`scripts/build_llama_release.py` builds an exact commit in
`<XFS>/runtimes/llama.cpp/v0.7.0/<backend>/build`, with a JSON build receipt.
It refuses dirty candidate source and never changes active executable links.
Vulkan builds completed on both hosts; the Bigcachy CUDA build also completed.
The shallow checkout reports build count 1; the exact commit identifies it.

`scripts/install_compute_env.py` prepares separate XFS environments, uses XFS
download caches and Python storage, and writes a frozen package list. Locations:

- Geekom: `/mnt/AI_Models/pytorch/rocm-10.1.0`.
- Bigcachy: `/mnt/xfs/AI_Models/pytorch/xpu-2.14.1`.
- OpenVINO: `/mnt/xfs/AI_Models/openvino/venv-2026.4.1`.

Both new PyTorch backends completed a 64×64 GPU tensor operation with zero
maximum error. NumPy is explicitly pinned for tensor/array interoperability.
No 7900 XT or B70 execution is certified by the APU/iGPU checks.

The OpenVINO candidate produced exactly the same BGE-M3 vectors as production
2026.4.0 on three compatibility samples: maximum difference 0, cosine >=0.99999.
It preserves the same weights, CLS pooling, L2 normalization, 1024 dimensions
and configured 8192-token maximum. Short iGPU translation, CPU Kokoro synthesis
(32400 finite samples at 24000 Hz) and NPU Whisper silence transcription completed.
Silence is a functional smoke check, not speech accuracy validation.

Following Bigcachy's reboot during the session, all four Intel service health
endpoints were healthy, and the embedding unit selected the versioned 2026.4.1
environment. The old unversioned OpenVINO venv is retained for rollback.

Runtime activation requires idle hardware or explicit restart approval before
unloading a resident model. The tracked launchers are
`geekom/llama-server-vulkan` and `rtx5080/llama-server-cuda`. Preserve the old
executable/link before promotion, pause admission with a revision-checked lease,
verify idle under the hardware lock, test a short authenticated request and
native slot geometry, then restore the previous residency/Off state and pause
ownership. A failed check must restore the prior launcher before reopening.

## Device separation before adding cards

Vulkan normally sees multiple GPUs. Its `GGML_VK_VISIBLE_DEVICES` accepts raw
enumeration indices, so hardcoding zero is unsafe after adding the Radeon.
`shared/vulkan_device.py` finds a unique vendor/device/type match on every
launch and derives the current index. It fails on missing or ambiguous hardware.
The Geekom launcher requires AMD 0x1002 / 0x1586 integrated graphics; it cannot
capture the external Radeon 0x744c. The wrapper was checked on the actual APU.

Intel translation now resolves the registered Arrow Lake iGPU UUID to its current
OpenVINO GPU number at startup. It must not move to the incoming Arc or the
NVIDIA device exposed by newer OpenVINO GPU enumeration. CPU embeddings and NPU
Whisper retain their explicit devices. Arc's future serving process needs its
own discrete-device binding (expected Intel 0xe223, verified after installation).

The future Radeon backend retains its physical unique-ID selection, rootless
Podman and pinned image until relocation tests. The Geekom model store and
container storage must use `/mnt/AI_Models`; the old laptop paths are invalid
there. Do not use HSA architecture spoofing or allow silent CPU fallback.

## Privileged work still requiring the operator

machine-setup's `scripts/prepare-compute-runtimes.sh <host> --system-plan` prints
reviewable root commands. Geekom needs Podman/rootless dependencies for the move.
Bigcachy's plan includes Intel compiler prerequisites for optional SYCL builds.
It uses full `pacman -Syu` transactions, avoiding partial Arch upgrades. No sudo
password is available to this session; do not claim those OS updates were applied.
Do not unload a live display driver or reboot active sessions automatically.

## Verified RTX activation

The RTX CUDA launcher was promoted under an admission pause and hardware lock.
All three existing fixed profiles passed short requests and exact native slot
geometry: OCR 32768, description 65536 and Qwen 65536 tokens, each one slot.
Both vision profiles correctly answered red for a 512×512 red-circle image.
The prior Qwen resident profile was restored and admission resumed. Fixed model
IDs and OpenCode windows are unchanged. The original executable is backed up
privately under the owner's XFS control directory for rollback.

## Verified Geekom activation

The user approved restarting despite five active requests. Geekom now uses the
pinned v0.7.0 Vulkan runtime through the APU-only launcher. Smart and Medium
passed short responses at 245760 tokens/five slots and 524288 tokens/three slots;
Flash Next passed at 245760 tokens/four slots. All reported the expected native
slot geometry and retain Q8 K/V. The previous Smart profile was restored.

Interrupted-request cleanup advanced the admission revision, so the final lease
resume correctly refused its stale revision. Inspection confirmed that the pause
still belonged to this activation; a fresh revision-checked resume reopened
admission. A subsequent authenticated public gateway request also passed.
These are functionality checks, not full-context quality or throughput results.

## Model page recovery after reboot

The Bigcachy HTTP gateway was running with the configured host binding but no
applied Docker port publication. Recreating only caddy-gateway restored the
models page and fourteen prepared Arc metrics. Infrastructure boot reconciliation
now checks the applied 192.168.2.2:8088 mapping and listener, recreating only that
gateway if its mapping is absent. A healthy gateway is left running. Local HTTP
403 is expected because the gateway trusts the edge host only.
