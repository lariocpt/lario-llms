#!/usr/bin/env bash

# Wait for Niri to be fully loaded
while ! niri msg workspaces >/dev/null 2>&1; do
    sleep 0.2
done

# Logging for debug
exec >/tmp/niri-startup.log 2>&1
set -x

echo "Starting Niri workspace configuration..."

# Helper to launch a command and move the resulting window to a specific workspace.
# Works by detecting the new window ID for a given app_id.
launch_on_workspace() {
    local target_ws="$1"
    local app_id="$2"
    shift 2
    local cmd=("$@")
    
    # Get list of existing window IDs for this app_id
    local pre_ids=$(niri msg --json windows | jq -r --arg app "$app_id" '.[] | select(.app_id == $app) | .id')
    
    # Launch the command fully detached, with all stdio pointed away from the
    # command-substitution pipe. Otherwise the long-lived GUI process inherits
    # this function's stdout (the $() pipe), so the caller's `id=$(...)` blocks
    # forever waiting for EOF that never comes (the app doesn't exit). That is
    # what hung the script right after the very first window. setsid also keeps
    # the launched app alive in its own session.
    setsid "${cmd[@]}" >/dev/null 2>&1 </dev/null &

    # Wait for the new window ID to appear
    for i in {1..50}; do
        local post_ids=$(niri msg --json windows | jq -r --arg app "$app_id" '.[] | select(.app_id == $app) | .id')
        local new_id=$(comm -13 <(echo "$pre_ids" | sort) <(echo "$post_ids" | sort) | head -n 1)
        if [ -n "$new_id" ] && [ "$new_id" != "null" ]; then
            # niri uses --window-id (not --id) for this action; <REFERENCE> is positional.
            niri msg action move-window-to-workspace --window-id "$new_id" "$target_ws"
            echo "$new_id"
            return 0
        fi
        sleep 0.2
    done
    return 1
}

# --- 1. PREPARATION PHASE ---
# Initialize Redthread workspaces if they don't exist
# The four t2-mono-{1..4} boards were removed 2026-08-07 with the Timbuk2 decommission.
for ws in system; do
    dir="/home/lario/.local/share/redthread_workspaces/$ws"
    file="$dir/redthread/notes.json"
    if [ ! -f "$file" ]; then
        mkdir -p "$(dirname "$file")"
        name="System TODO"
        cat <<EOF > "$file"
{
  "schemaVersion": 4,
  "activeIdx": 0,
  "boards": [
    {
      "name": "$name",
      "notes": [],
      "strings": []
    }
  ]
}
EOF
    fi
done

# --- 2. CONFIG LOAD PHASE ---
# Load and execute layout configurations from ~/.config/niri-wspaces/
WSPACE_DIR="/home/lario/.config/niri-wspaces"
if [ -d "$WSPACE_DIR" ]; then
    # Sort files to guarantee a deterministic loading order
    for ws_file in $(find "$WSPACE_DIR" -maxdepth 1 -type f | sort); do
        echo "Processing workspace config: $ws_file"
        
        current_ws=""
        
        while IFS= read -r line || [ -n "$line" ]; do
            # Trim whitespace
            line=$(echo "$line" | xargs)
            
            # Skip comments and empty lines
            [ -z "$line" ] && continue
            [[ "$line" =~ ^# ]] && continue
            
            # Check for directives
            if [[ "$line" =~ ^@workspace[[:space:]]+(.*) ]]; then
                current_ws="${BASH_REMATCH[1]}"
                echo "Switching target workspace to: $current_ws"
                continue
            elif [[ "$line" =~ ^@action[[:space:]]+(.*) ]]; then
                action_cmd="${BASH_REMATCH[1]}"
                echo "Running action: $action_cmd"
                eval "$action_cmd"
                continue
            fi
            
            # Window launch: app_id | command [| env_vars [| var_name]]
            # Split by |
            IFS='|' read -r app_id cmd env_vars var_name <<< "$line"
            app_id=$(echo "$app_id" | xargs)
            cmd=$(echo "$cmd" | xargs)
            env_vars=$(echo "$env_vars" | xargs)
            var_name=$(echo "$var_name" | xargs)
            
            [ -z "$app_id" ] || [ -z "$cmd" ] && continue
            
            echo "Launching $app_id (cmd: $cmd) on workspace: $current_ws"
            
            win_id=""
            if [ -n "$env_vars" ]; then
                win_id=$(eval "export $env_vars; launch_on_workspace \"\$current_ws\" \"\$app_id\" $cmd")
            else
                win_id=$(eval "launch_on_workspace \"\$current_ws\" \"\$app_id\" $cmd")
            fi
            
            if [ -n "$var_name" ] && [ -n "$win_id" ]; then
                eval "$var_name=\"$win_id\""
                echo "Captured ID for $var_name: $win_id"
            fi
            
        done < "$ws_file"
    done
else
    echo "Warning: workspace configuration directory $WSPACE_DIR not found."
fi

echo "Configuration completed!"
