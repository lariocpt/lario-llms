# Niri Agent Fleet Shortcuts

This document describes the hotkeys and implementations used to quickly route desktop data into Lario's local Agent Fleet via the Niri window manager.

## Keybinds

These keybinds are registered in `~/.config/niri/config.kdl` under the `binds` block, and will appear in the Niri Hotkey Overlay (`Super + ?` / `Mod+Shift+Slash`).

- **`Super + Shift + H`**: Open Lario Agent Fleet
  - Opens a floating terminal menu via `fuzzel` or native select.
  - Allows you to choose an active agent (from `~/Projects/personal/agents/hermes/`).
  - Drops into an interactive `hermes-cli` session with that agent.

- **`Super + Shift + 6`**: Send Screenshot to Agent Fleet
  - Freezes the screen and opens an interactive crosshair overlay (using `slurp` + `grim`).
  - Prompts you to pick an agent from the fleet.
  - Sends the cropped screenshot as an initial visual query to the chosen agent.
  - Opens a terminal to continue the conversation interactively.

- **`Super + Shift + V`**: Send Text Clipboard to Agent Fleet
  - Grabs your current text clipboard (using `wl-paste`).
  - Prompts you to pick an agent from the fleet.
  - Sends the clipboard contents as an initial text payload.
  - Opens a terminal to continue the conversation interactively.

## Underlying Script (`lario-fleet`)

The keybinds spawn `~/.local/bin/lario-fleet`, but the logic lives in
`~/Projects/personal/agents/deploy/lario-fleet.sh` (agents repo, bigcachy-only; its advisory
cap is read live from `agent-model slots`). On bigcachy `~/.local/bin/lario-fleet` is a symlink
to that script (made by `agents/deploy/boot-fleet.sh`); the `niri-post-setup/bin/lario-fleet`
shipped to every other machine by the bin mirror is a thin launcher that execs it, or exits 1
with a notification where the agents repo is absent (since 2026-08-31 — before that it was a
full copy that could go stale).

### How it works
1. **Interactive UI**: It polls Docker to find all running `hermes-*-agent` containers.
2. **Context Handling**: 
   - `--vision`: Uses `slurp` and `grim` to save `/tmp/lario_fleet_snap.png`.
   - `--text`: Uses `wl-paste` to save `/tmp/lario_fleet_text.txt`.
3. **Execution**: It uses `docker cp` to inject the payload directly into the target container, executes a single silent query (`hermes chat -q`) to pass the data, and then immediately drops the user into an interactive session (`hermes chat -c`).
