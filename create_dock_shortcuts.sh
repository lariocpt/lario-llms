#!/usr/bin/env bash

set -euo pipefail

# Directories
APPLICATIONS_DIR="$HOME/.local/share/applications"
mkdir -p "$APPLICATIONS_DIR"

# 1. Open Design Desktop Entry
OPEN_DESIGN_PATH="$HOME/open-design"
OPEN_DESIGN_ICON="$OPEN_DESIGN_PATH/docs/assets/logo.png"
OPEN_DESIGN_DESKTOP="$APPLICATIONS_DIR/open-design.desktop"

if [ -d "$OPEN_DESIGN_PATH" ]; then
    echo "Creating Open Design desktop entry..."
    cat << EOF > "$OPEN_DESIGN_DESKTOP"
[Desktop Entry]
Name=Open Design
Comment=Start Open Design Web Service
Exec=bash -c "cd $OPEN_DESIGN_PATH && pnpm tools-dev run web"
Icon=$OPEN_DESIGN_ICON
Terminal=true
Type=Application
Categories=Development;Design;
Keywords=design;agent;ai;opencode;
EOF
    chmod +x "$OPEN_DESIGN_DESKTOP"
    echo "✓ Open Design shortcut created at $OPEN_DESIGN_DESKTOP"
else
    echo "⚠ Open Design directory not found at $OPEN_DESIGN_PATH"
fi

# 2. Palot (Dev) Desktop Entry
PALOT_PATH="$HOME/palot"
PALOT_ICON="$PALOT_PATH/apps/desktop/resources/icon.png"
PALOT_DESKTOP="$APPLICATIONS_DIR/palot-dev.desktop"

if [ -d "$PALOT_PATH" ]; then
    echo "Creating Palot (Dev) desktop entry..."
    cat << EOF > "$PALOT_DESKTOP"
[Desktop Entry]
Name=Palot (Dev)
Comment=Start Palot in Developer Mode
Exec=bash -c "cd $PALOT_PATH/apps/desktop && bun run dev"
Icon=$PALOT_ICON
Terminal=false
Type=Application
Categories=Development;IDE;
StartupWMClass=Palot
Keywords=palot;opencode;ai;agent;
EOF
    chmod +x "$PALOT_DESKTOP"
    echo "✓ Palot (Dev) shortcut created at $PALOT_DESKTOP"
else
    echo "⚠ Palot directory not found at $PALOT_PATH"
fi

# Update desktop database
if command -v update-desktop-database &> /dev/null; then
    update-desktop-database "$APPLICATIONS_DIR"
fi

echo "🎉 Done! Both applications should now appear in your application launcher and can be pinned to your dock."
