"""The G502 button map: names, ratbag indices and diagram positions.

Positions are fractions of the diagram image's width and height, so the
overlay scales with whatever size the image is drawn at. They were measured
against images/g502.png (1024x555).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ButtonSpot:
    index: int
    name: str
    g_name: str
    x: float
    y: float


# Ratbag indices, from docs/button-map.md. The tilt wheel and profile button
# are numbered differently from the manual, which is why this table exists.
#
# Positions were extracted from the leader lines in images/g502.png: each
# line's tip marks the button, and the label at its other end gives the
# ratbag index. Verified by drawing the hotspots back onto the image.
BUTTONS: tuple[ButtonSpot, ...] = (
    ButtonSpot(0, "Left click", "", 0.3232, 0.6288),
    ButtonSpot(1, "Right click", "", 0.2402, 0.5315),
    ButtonSpot(2, "Wheel click", "", 0.3604, 0.3982),
    ButtonSpot(3, "Back", "G4", 0.8379, 0.4072),
    ButtonSpot(4, "Forward", "G5", 0.8350, 0.4685),
    ButtonSpot(5, "DPI Shift", "G6", 0.7822, 0.6811),
    ButtonSpot(6, "DPI Down", "G7", 0.5566, 0.5009),
    ButtonSpot(7, "DPI Up", "G8", 0.4736, 0.6054),
    ButtonSpot(8, "Profile select", "G9", 0.5137, 0.1081),
    ButtonSpot(9, "Scroll right", "", 0.3398, 0.3802),
    ButtonSpot(10, "Scroll left", "", 0.4023, 0.4324),
)

BY_INDEX = {spot.index: spot for spot in BUTTONS}


def describe(index: int) -> str:
    spot = BY_INDEX.get(index)
    if spot is None:
        return f"Button {index}"
    if spot.g_name:
        return f"{spot.name} ({spot.g_name})"
    return spot.name
