# Niri Agent Fleet Shortcuts

This document describes the hotkeys and implementations used to quickly route desktop data into Lario's local Agent Fleet via the Niri window manager.

## Keybinds

These keybinds are registered in `~/.config/niri/config.kdl` under the `binds` block, and will appear in the Niri Hotkey Overlay (`Super + ?` / `Mod+Shift+Slash`).

- **`Super + Shift + H`**: Open Lario Agent Fleet
  - Opens a floating terminal menu via `fuzzel` or native select.
  - Allows you to choose an active agent (from `/mnt/Shared/personal/agents/hermes/`).
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

The core logic is handled by a single unified script: `~/.local/bin/lario-fleet`

### How it works
1. **Interactive UI**: It polls Docker to find all running `hermes-*-agent` containers.
2. **Context Handling**: 
   - `--vision`: Uses `slurp` and `grim` to save `/tmp/lario_fleet_snap.png`.
   - `--text`: Uses `wl-paste` to save `/tmp/lario_fleet_text.txt`.
3. **Execution**: It uses `docker cp` to inject the payload directly into the target container, executes a single silent query (`hermes chat -q`) to pass the data, and then immediately drops the user into an interactive session (`hermes chat -c`).
