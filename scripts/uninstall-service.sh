#!/usr/bin/env bash
# Remove the LinGHub user service installed by install-service.sh.
set -euo pipefail

UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_PATH="$UNIT_DIR/linghub-dev.service"
TRAY_UNIT_PATH="$UNIT_DIR/linghub-dev-tray.service"

if [ -e "$TRAY_UNIT_PATH" ]; then
    systemctl --user disable --now linghub-dev-tray.service 2>/dev/null || true
    rm -f "$TRAY_UNIT_PATH"
    echo "Removed $TRAY_UNIT_PATH"
fi

if [ -e "$UNIT_PATH" ]; then
    systemctl --user disable --now linghub-dev.service 2>/dev/null || true
    rm -f "$UNIT_PATH"
    echo "Removed $UNIT_PATH"
fi

systemctl --user daemon-reload
