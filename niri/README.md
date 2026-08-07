# Niri Work-Session Startup Configuration

This directory holds the custom workspace and startup configuration for the
[Niri](https://niri-wm.github.io/niri) scrollable-tiling Wayland compositor.
On login it lays out a fixed set of named workspaces, each pre-populated with
the applications for a particular context: system monitoring, a scratch
`playground`, and four `T2 Mono` project workspaces.

> Tested with **niri 26.04**. The files here are the source of truth; the live
> copies that niri actually runs live in `~/.config/niri/` (see
> [How to duplicate](#how-to-duplicate-this-configuration)).

## Directory Contents

*   [`config.kdl`](file:///home/lario/lario-llms/niri/config.kdl) — the Niri configuration file. It declares the named workspaces, registers the startup script via `spawn-sh-at-startup`, and defines the macOS-style screenshot/video recording bindings.
*   [`keybinds.kdl`](file:///home/lario/lario-llms/niri/keybinds.kdl) — separate/modular keybindings declarations.
*   [`startup.sh`](file:///home/lario/lario-llms/niri/startup.sh) — the bash script Niri runs at login to prepare data directories, launch session applications, and lay out workspaces.
*   [`populate-workspaces`](file:///home/lario/lario-llms/niri/populate-workspaces) — helper script used to pre-populate local browser windows and Flatpak apps.
*   [`niricritty-record`](file:///home/lario/lario-llms/niri/niricritty-record) — screen recording toggle script using `wf-recorder` and `libnotify`.
*   [`niri-wspaces/`](file:///home/lario/Projects/personal/lario-llms/niri-wspaces/) — directory containing individual, modular workspace configuration files (e.g., `system`, `playground`).

---

## Dynamic Workspace Configurations (`niri-wspaces/`)

Instead of hardcoding workspace logic and commands directly in the `startup.sh` script, it parses files found inside `~/.config/niri-wspaces/`. Each file defines the layout and commands for a given workspace.

### Config File Format:
*   Lines starting with `#` or empty lines are ignored.
*   **Directives**:
    *   `@workspace <name>` — Sets the target workspace for subsequent app launches (e.g., `@workspace system`).
    *   `@action <command>` — Executes an arbitrary bash command (with dynamic variable expansion for captured window IDs).
*   **Window Launch Lines**:
    *   `app_id | command [| env_vars [| var_name]]`
    *   *Example*: `com.mitchellh.ghostty | ghostty --title="system-clock" -e tuime | | clock_id`
    *   This launches the app under the current target workspace, optionally setting environment variables, and captures the resulting window ID into `var_name` for use in subsequent `@action` lines.

---

## How `startup.sh` Works

The heart of the script is the helper
`launch_on_workspace <workspace> <app_id> <command...>`:

1.  Snapshots the existing window IDs for `<app_id>` (via `niri msg --json windows | jq`).
2.  Launches `<command>` **fully detached** — `setsid <command> >/dev/null 2>&1 </dev/null &`.
3.  Polls (up to ~10 s) for a *new* window ID of that `app_id`, moves it with
    `niri msg action move-window-to-workspace --window-id <id> <workspace>`, and
    prints the ID so the caller can capture it (used to merge the clock/monitor column).

Two details here are load-bearing and easy to get wrong:

*   **Launched apps must be detached with their stdio redirected.** Each call
    site captures the new window ID with `id=$(launch_on_workspace ...)`. If the
    backgrounded GUI app keeps the function's stdout — which, inside `$(...)`, is
    the command-substitution pipe — open, then `$(...)` blocks **forever** waiting
    for an EOF that never comes (the app does not exit). The symptom is "the
    script creates the first window, then nothing else happens." Using
    `setsid ... >/dev/null 2>&1 </dev/null &` both avoids the hang and keeps the
    app alive in its own session.
*   **The move action's flag is `--window-id`, not `--id`.** (Note that
    `focus-window` *does* use `--id` — the two actions differ. When in doubt run
    `niri msg action <name> --help`.)

A `set -x` execution trace is written to `/tmp/niri-startup.log` for debugging.

---

## Workspace Layouts

### 1. `system` Workspace
*   **Left 50%**: one column split vertically — `tuime` (clock) on top, `zenith` (system monitor) on the bottom.
*   **Right 50%**: `redthread` TUI board (the default `"System TODO"` board).
*   **Scroll space (to the right)**: a Google Chrome window, followed by a Sublime Text window.

### 2. `playground` Workspace
In order: the `gram` editor, then Google Chrome, then a plain `ghostty` terminal,
then a terminal running the `harlequin` SQL client.

### 3. Per-project workspaces (none defined right now)

There were four — `T2 Mono 1` … `T2 Mono 4` — removed on 2026-08-07 with the Timbuk2
decommission. The shape is worth keeping as a template. Each was populated, in order, with:
*   **redthread** — opened with an isolated `XDG_DATA_HOME` pointing at
    `~/.local/share/redthread_workspaces/<project>`, showing a per-project board.
*   **Croft** — opened in a terminal at the project directory.
*   **Google Chrome** — a new window.
*   **cline** — launched in a terminal inside the project directory (commented out).
*   **Terminal** — a plain terminal opened at the project directory.

The `redthread` board files (`notes.json`, schema v4) are created automatically
on first run if they don't already exist, by the prep loop at the top of `startup.sh`.

> A caution learned from those four: their configs pointed at `/home/lario/timbuk2/...`,
> a path that stopped existing when the repos moved under `~/Projects/`. Nothing failed
> loudly — `ghostty --working-directory=<missing>` just opens somewhere else — so they sat
> broken and unnoticed. If you add a project workspace, verify the directory exists.

---

## Dependencies

*   **Compositor & tooling**: `niri` (26.04+), `jq`, coreutils (`comm`), util-linux (`setsid`).
*   **Terminal & GUI apps**: `ghostty`, `google-chrome`, Sublime Text (Flatpak `com.sublimehq.SublimeText`), `gram` (`app.liten.Gram`).
*   **TUI apps**: `tuime`, `zenith`, `redthread`, `harlequin`, `cline`, `croft`.
*   **Screenshot & Screen Recording**: `grim`, `slurp`, `swappy`, `wf-recorder`, `libnotify`.
*   **Bluetooth manager (GUI)**: `blueman` (provides `blueman-applet` and `blueman-manager`).

---

## Bluetooth Configuration

To use the integrated Bluetooth applet and manager (configured via `spawn-at-startup "blueman-applet"` and `Mod+Shift+B` / `Super+Shift+B` in `config.kdl`):

1. **Install Blueman** (Fedora):
   ```bash
   sudo dnf install -y blueman
   ```
2. **Start the applet** (without logging out/restarting):
   ```bash
   nohup blueman-applet >/dev/null 2>&1 &
   ```


---

## How to Duplicate This Configuration

### 1. Install the dependencies
Install everything listed above on the target machine. For Fedora, you can run:
```bash
sudo dnf install niri fuzzel ghostty waybar swaybg xdg-desktop-portal-gnome xdg-desktop-portal-gtk grim slurp swappy wf-recorder libnotify
```

### 2. Adjust the hard-coded paths
These files contain absolute, user-specific paths — edit them before use:
*   `config.kdl` → `spawn-sh-at-startup "/home/lario/.config/niri/startup.sh"`
*   `startup.sh` → `/home/lario/.local/share/redthread_workspaces/...`
*   `niri-wspaces/<name>` → any `--working-directory` in a project workspace config

### 3. Copy the files into the Niri config directory
```bash
# Back up any existing config first
cp ~/.config/niri/config.kdl ~/.config/niri/config.kdl.bak

cp config.kdl ~/.config/niri/config.kdl
cp keybinds.kdl ~/.config/niri/keybinds.kdl
cp startup.sh ~/.config/niri/startup.sh
chmod +x ~/.config/niri/startup.sh

# Copy modular workspace configurations
mkdir -p ~/.config/niri-wspaces
cp -r niri-wspaces/* ~/.config/niri-wspaces/

# Copy executable binaries to user's bin path
mkdir -p ~/.local/bin
cp populate-workspaces ~/.local/bin/populate-workspaces
cp niricritty-record ~/.local/bin/niricritty-record
chmod +x ~/.local/bin/populate-workspaces ~/.local/bin/niricritty-record
```

### 4. Verify the app IDs, then restart Niri
Confirm the `app_id` values in `startup.sh` match your system (see
Troubleshooting), then reload or restart your Niri session. The compositor runs
`startup.sh` on login, which prepares the data directories and positions every
window.

---

## Troubleshooting

*   **Nothing launches, or it stops after the first window.** Almost always the
    detached-launch requirement described in [How it works](#how-startupsh-works).
    Inspect `/tmp/niri-startup.log`.
*   **A window opens but lands on the wrong workspace (or not at all).** Its
    `app_id` in the script doesn't match reality. Launch the app, then run
    `niri msg --json windows | jq -r '.[].app_id'` to read the real value and
    update the script. Current assumptions: `ghostty` (`com.mitchellh.ghostty`), `google-chrome`,
    `sublime_text`, `app.liten.Gram`.
*   **A slow app (Flatpak Sublime) isn't routed.** It didn't open a
    window within the ~10 s poll window (50 × 0.2 s). Increase the loop count in
    `launch_on_workspace`.
*   **A `niri msg action` flag is rejected.** Action flags vary between niri
    versions; this config targets **niri 26.04**. Check `niri msg action <name> --help`.

---

## Ghostty & Yazi Terminal Integration

This configuration has been migrated from **Kitty** to **Ghostty**.

### 1. Niri and Workspace Integration
* **Keybindings:** `Mod+T` spawns a Ghostty window. `Mod+Y` spawns Yazi inside a Ghostty window (`ghostty -e yazi`).
* **Workspaces:** All terminal/TUI windows in `startup.sh` (tuime, zenith, redthread, croft, and plain shells) are launched using `ghostty`. Niri rules identify them via their `app_id` (`com.mitchellh.ghostty`).

### 2. Random Theme on Launch
A custom wrapper script is installed at `~/.local/bin/ghostty` (which takes precedence over `/usr/bin/ghostty` on the user's `PATH`).
* On every normal launch, the wrapper queries Ghostty's available themes and picks one at random (`ghostty --theme="..."`).
* Subcommands (like `+list-themes`) and manual theme overrides (`--theme=...`) bypass the random selection.

### 3. Yazi Integration
* **Opener:** Yazi's `yazi.toml` is configured to launch a new Ghostty window at the selected path when opening a directory in a terminal (`ghostty --working-directory="$1"`).
* **Media Previews:** Ghostty's native support for the Kitty Graphics Protocol allows Yazi to preview images, PDF thumbnails (`pdftoppm`), and video frames (`ffmpegthumbnailer`) directly inside the terminal window without any additional plugins.
