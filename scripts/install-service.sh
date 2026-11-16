#!/usr/bin/env bash
# Install the LinGHub user service.
#
# The unit's ExecStart must point at an interpreter that can import linghub.
# A virtualenv's console script hardcodes its own path, so this script writes
# the unit with the resolved interpreter rather than assuming /usr/bin/linghub
# exists.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_PATH="$UNIT_DIR/linghub.service"
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

sed "s|^ExecStart=.*|ExecStart=$PYTHON -m linghub.cli run|" \
    "$REPO_DIR/data/linghub.service" > "$UNIT_PATH"

systemctl --user daemon-reload
systemctl --user enable --now linghub.service

echo "Installed $UNIT_PATH"
echo "Check status with: systemctl --user status linghub.service"
echo "Follow logs with:  journalctl --user -u linghub.service -f"
