#!/usr/bin/env bash
# Install the LinGHub user service for a clone install.
#
# The unit is named linghub-dev.service, not linghub.service: a packaged
# install owns that name in /usr/lib/systemd/user, and a unit in the user
# directory shadows one in the system directory. Two installs of the same app
# must not fight over one unit name.
#
# The unit's ExecStart must point at an interpreter that can import linghub.
# A virtualenv's console script hardcodes its own path, so this script writes
# the unit with the resolved interpreter rather than assuming /usr/bin/linghub
# exists.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_PATH="$UNIT_DIR/linghub-dev.service"
TRAY_UNIT_PATH="$UNIT_DIR/linghub-dev-tray.service"
PYTHON="${LINGHUB_PYTHON:-$REPO_DIR/.venv/bin/python}"

if [ ! -x "$PYTHON" ]; then
    echo "Error: no interpreter at $PYTHON" >&2
    echo "Create the venv first: python3 -m venv .venv && .venv/bin/pip install -e ." >&2
    exit 1
fi

if ! "$PYTHON" -c "import linghub" 2>/dev/null; then
    echo "Error: $PYTHON cannot import linghub" >&2
    echo "Install the package into it: $PYTHON -m pip install -e $REPO_DIR" >&2
    exit 1
fi

mkdir -p "$UNIT_DIR"

sed "s|^ExecStart=.*|ExecStart=$PYTHON -m linghub.cli run|; \
     s|^ExecStartPre=.*|ExecStartPre=-$PYTHON -m linghub.cli init --if-missing|" \
    "$REPO_DIR/data/linghub-dev.service" > "$UNIT_PATH"

# The tray is optional: it needs a graphical session and a StatusNotifier host,
# and a headless machine has neither.
INSTALL_TRAY="${LINGHUB_TRAY:-ask}"

if [ "$INSTALL_TRAY" = "ask" ]; then
    if [ -t 0 ]; then
        read -r -p "Install the tray icon service? [y/N] " reply
        case "$reply" in
            [yY]*) INSTALL_TRAY=yes ;;
            *) INSTALL_TRAY=no ;;
        esac
    else
        INSTALL_TRAY=no
    fi
fi

if [ "$INSTALL_TRAY" = "yes" ]; then
    sed "s|^ExecStart=.*|ExecStart=$PYTHON -m linghub.cli tray|" \
        "$REPO_DIR/data/linghub-dev-tray.service" > "$TRAY_UNIT_PATH"
fi

systemctl --user daemon-reload
systemctl --user enable --now linghub-dev.service

if [ "$INSTALL_TRAY" = "yes" ]; then
    systemctl --user enable --now linghub-dev-tray.service
    echo "Installed $TRAY_UNIT_PATH"
fi

echo "Installed $UNIT_PATH"
echo "Check status with: systemctl --user status linghub-dev.service"
echo "Follow logs with:  journalctl --user -u linghub-dev.service -f"
