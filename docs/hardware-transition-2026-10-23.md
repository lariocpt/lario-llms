# Radeon cutover — 2026-10-24

The RX 7900 XT is physically installed on l-dev-ai through the spare M.2 NVMe
slot. The sole canonical registry, provider, CLI and service name is
`geekom7900xt`. The laptop `7900xt`, `winmax7900xt` and prepared `gkm7900xt`
placements are retired; their source history is in `attic/7900xt-laptop/`.

Source changes cover modelctl, fixed profile IDs, admission, lifecycle recovery,
OpenCode overlays on all three clients, model MCP catalogs, telemetry, and the
optional Docker compatibility forwarder used by Hermes (`agent-llm:8080`).
The forwarder is an HTTP client only; no GPU or model storage is assigned to it.

Endpoints use l-dev-ai's fleet address from machine-setup/lib/fleet.sh: loopback
for the owner, tailnet for other clients, public port 11436, private backend
127.0.0.1:11446. Moving inference does not require changing IP routes or DHCP.
Preserve existing fleet networking. Weights, Podman graph storage and the pinned
llama-swap binary belong on /mnt/AI_Models (XFS).

## Remaining host deployment and acceptance

This editing session sees the PCI GPU but exposes the model mount read-only,
denies the user systemd bus, and cannot resolve package mirrors. No live service
cutover, credential distribution, remote deployment or inference is claimed.
The separately managed Hermes repository is not present in this workspace.

1. Sync the reviewed changes in both repositories to all three clients. On the
   laptop, disable/stop the retired `7900xt.service`, `gkm7900xt.service`,
   `winmax7900xt.service` and matching admission instances if installed. Preserve
   private credentials and snapshots before retiring the files.
2. On l-dev-ai, apply machine-setup's reviewed SYSTEM output for Podman/crun and
   user lingering. Stage the pinned llama-swap binary, pinned ROCm image and all
   registered weights on writable XFS. The runtime uses --pull=never and a new
   dedicated Podman graph root, so an image in another store is insufficient.
3. Prepare new owner credentials outside the repository, explicitly choosing the
   validated profile and owner listen addresses:

   ```bash
   python3 shared/admission/provision.py geekom7900xt \
     --output ~/.config/lario-geekom7900xt-prepared \
     --listen 127.0.0.1 --listen 100.68.129.20 \
     --model qwen3.8 --preset fast-128k
   ```

   Install the generated geekom7900xt private env/key files mode 0600 in
   ~/.config/lario-admission. Retain credentials.json privately for rollback and
   client distribution. Never print or commit its contents.
4. Run machine-setup/shared/models/install-lifecycle.sh l-dev-ai. It validates
   the XFS UUID, installs the runtime and admission units, and conditionally
   starts them. This does not restart the Geekom Vulkan model.
5. Distribute/register scoped client credentials with the existing authenticated
   control provisioner, update fleet-clients.json and the managed Hermes source,
   and render client configurations. Replace retired private provider keys only
   after the new gateway accepts the corresponding credentials. Regenerated
   fixed profile IDs require explicit session migration through OpenCode's API;
   do not modify its databases directly.
6. On bigcachy, update geekom7900xt.forwarder.env privately with
   LARIO_RADEON_UPSTREAM=http://100.68.129.20:11436 and the matching fleet key.
   Recreate only radeon-forwarder after checking consumers are idle. Its DNS
   alias remains agent-llm. Retire the old 7900xt.forwarder.env afterwards.
7. Verify the physical GPU UUID, ROCm-only device enumeration, authenticated
   /v1/models and an actual completion from each client. Check /budget and model
   MCP report l-dev-ai and the expected profile. Verify one isolated Hermes tool
   call, monitoring labels, stop/start intent and automatic boot recovery.
   Keep acceptance pending until those checks succeed.

## Validation in this session

- 61 focused LLM placement/runtime/lifecycle/client tests passed.
- The machine-setup test suite passed, including fleet endpoint rendering.
- l-dev-ai full provisioning dry-run passed. mini-mobile and bigcachy full dry-runs
  reached the existing artwork step and stopped because Noctalia settings.json
  is absent in this workspace. Their lifecycle dry-runs and client-rendering
  tests passed.
- Changed Python and shell scripts compile/parse; git diff whitespace checks pass.
- Full LLM discovery ran 198 tests: one existing Geekom model-count mismatch
  (baseline registry contains six, test expects five), seven errors requiring
  unavailable aiohttp, and one skip. Package installation failed on DNS access.
- The canonical CLI lists all three Radeon models. Physical runtime acceptance
  remains pending; the GPU identity/compute guard refuses this session's device
  view, rather than falling back to CPU or the iGPU.
