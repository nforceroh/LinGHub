"""The G502 button map: names, ratbag indices and diagram positions.

Positions come from hotspots.json, which `linghub hotspots` writes when you
place the markers by hand. The built-in fallback is only used when that file
is missing, so the diagram still renders before anyone has placed them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


HOTSPOTS_FILE = Path(__file__).resolve().parent / "hotspots.json"


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

# Used only when hotspots.json is absent. These were measured against
# images/g502.png, which has a different crop from g502_trans.png, so they are
# approximate on the base image. Run `linghub hotspots` to place them exactly.
FALLBACK_POSITIONS: dict[int, tuple[float, float]] = {
    0: (0.1925, 0.6573),
    1: (0.1316, 0.5626),
    2: (0.2197, 0.4327),
    3: (0.5698, 0.4415),
    4: (0.5676, 0.5012),
    5: (0.5290, 0.7082),
    6: (0.3636, 0.5327),
    7: (0.3027, 0.6345),
    8: (0.3321, 0.1503),
    9: (0.2046, 0.4152),
    10: (0.2505, 0.4661),
}


def load_positions(path: Path = HOTSPOTS_FILE) -> dict[int, tuple[float, float]]:
    """Read placed hotspots, falling back to the built-in positions."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(FALLBACK_POSITIONS)

    positions = {}
    for entry in data.get("hotspots", []):
        try:
            positions[int(entry["index"])] = (float(entry["x"]), float(entry["y"]))
        except (KeyError, TypeError, ValueError):
            continue
    return positions or dict(FALLBACK_POSITIONS)


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
