#!/usr/bin/env bash
# Remove the LinGHub user service.
set -euo pipefail

UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_PATH="$UNIT_DIR/linghub.service"

systemctl --user disable --now linghub.service 2>/dev/null || true
rm -f "$UNIT_PATH"
systemctl --user daemon-reload

echo "Removed $UNIT_PATH"
