"""The G502 button map: names, ratbag indices and diagram positions.

Positions come from hotspots.json, which `linghub hotspots` writes when you
place the markers by hand. The packaged file is the fallback, and the built-in
positions are the fallback below that, so the diagram still renders before
anyone has placed them.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


# Shipped inside the package: read-only once installed.
PACKAGED_HOTSPOTS = Path(__file__).resolve().parent / "hotspots.json"

# The diagram the hotspots are placed on, shipped inside the package so a
# wheel and an RPM find it the same way.
DIAGRAM_IMAGE = Path(__file__).resolve().parent / "images" / "g502_trans.png"


def user_hotspots() -> Path:
    """Where `linghub hotspots` writes: user data, not configuration.

    The package directory is read-only in a packaged install, and these are
    placed positions rather than settings, so they belong in the XDG data
    directory. ADR-0004 keeps `~/.config/linghub/` holding the one config file.
    """
    data_home = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(data_home) / "linghub" / "hotspots.json"


def hotspots_file() -> Path:
    """The file to read: the user's own if they have placed any, else the packaged one."""
    user = user_hotspots()
    return user if user.exists() else PACKAGED_HOTSPOTS


@dataclass(frozen=True)
class ButtonSpot:
    index: int
    name: str
    g_name: str
    x: float
    y: float


# Names and ratbag indices, from docs/button-map.md. The tilt wheel and
# profile button are numbered differently from the manual, which is why this
# table exists.
NAMES: tuple[tuple[int, str, str], ...] = (
    (0, "Left click", ""),
    (1, "Right click", ""),
    (2, "Wheel click", ""),
    (3, "Back", "G4"),
    (4, "Forward", "G5"),
    (5, "DPI Shift", "G6"),
    (6, "DPI Down", "G7"),
    (7, "DPI Up", "G8"),
    (8, "Profile select", "G9"),
    (9, "Scroll right", ""),
    (10, "Scroll left", ""),
)


# The owner's manual numbers the buttons 1-12 in a different order from
# ratbag, so the UI needs both to be readable. Kept separate from NAMES
# because it is a display-only lookup: nothing in the config or on the wire
# uses these numbers.
_MANUAL_ORDER: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6, 7, 10, 9, 8)

MANUAL: dict[int, int] = {
    index: manual for manual, index in enumerate(_MANUAL_ORDER, start=1)
}

# Used only when hotspots.json is absent, so the diagram still works before
# anyone has placed a marker. These match the packaged hotspots.json, which is
# measured against g502_trans.png as it ships. Replacing that image means
# re-placing them: run `linghub hotspots`.
FALLBACK_POSITIONS: dict[int, tuple[float, float]] = {
    0: (0.2364, 0.7331),
    1: (0.0781, 0.6400),
    2: (0.3067, 0.3416),
    3: (0.8173, 0.4305),
    4: (0.6957, 0.5651),
    5: (0.6306, 0.7935),
    6: (0.5658, 0.5042),
    7: (0.4268, 0.6881),
    8: (0.4912, 0.1439),
    9: (0.1841, 0.4269),
    10: (0.3025, 0.5156),
}


def load_positions(path: Path | None = None) -> dict[int, tuple[float, float]]:
    """Read placed hotspots, over the built-in positions.

    Merged rather than replaced: a user file holding one placed button must
    not drop the other ten, which is what returning only its entries did.
    """
    positions = dict(FALLBACK_POSITIONS)
    try:
        data = json.loads((path or hotspots_file()).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return positions

    for entry in data.get("hotspots", []):
        try:
            positions[int(entry["index"])] = (float(entry["x"]), float(entry["y"]))
        except (KeyError, TypeError, ValueError):
            continue
    return positions


def _build() -> tuple[ButtonSpot, ...]:
    positions = load_positions()
    spots = []
    for index, name, g_name in NAMES:
        x, y = positions.get(index, FALLBACK_POSITIONS[index])
        spots.append(ButtonSpot(index, name, g_name, x, y))
    return tuple(spots)


BUTTONS: tuple[ButtonSpot, ...] = _build()
BY_INDEX = {spot.index: spot for spot in BUTTONS}


def describe(index: int) -> str:
    spot = BY_INDEX.get(index)
    if spot is None:
        return f"Button {index}"
    if spot.g_name:
        return f"{spot.name} ({spot.g_name})"
    return spot.name


def manual_number(index: int) -> str:
    """The owner's manual number for a ratbag index, or a dash if unknown."""
    return str(MANUAL.get(index, "-"))
