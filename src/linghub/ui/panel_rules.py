"""The rules the panels obey, kept out of the callbacks that apply them.

Both panels are mostly widget wiring, but each holds one piece of real
knowledge: the DPI panel enforces that only one slot is the default, and the
lighting panel converts between a duration in milliseconds and a speed slider
and decides which controls an effect enables.

Inside a GTK callback those rules can only be tested by building the widget.
Here they are plain functions, so the arithmetic and the exclusivity get their
own tests and the panels are left with wiring.

The speed conversion is the one most worth pinning down: it is inverted, so
getting it backwards makes "fast" mean "slow" and nothing crashes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


# The speed slider's range. Higher means faster, which is a *shorter* duration.
SPEED_MIN = 1
SPEED_MAX = 20

# The duration that sits at speed 10, and the scale everything else hangs off:
# a speed of 1 means one 20-second cycle, a speed of 20 means a 1-second one.
DURATION_AT_UNIT_SPEED = 20_000

# The speed shown for a duration the hardware will not report.
FALLBACK_SPEED = 10

# The effects that loop, and so have a speed. A fixed colour does not move.
ANIMATED_MODES: tuple[str, ...] = ("cycle", "breathing")

# The four modes every supported G502 reports, in libratbag's order. The
# labels are here because the *order* is hardware fact and the panel must not
# reorder it; which effect animates is derived from the names above.
MODES: tuple[tuple[str, str], ...] = (
    ("off", "Off"),
    ("on", "Fixed colour"),
    ("cycle", "Cycle colours"),
    ("breathing", "Breathing"),
)


def duration_to_speed(duration: int) -> float:
    """Map a duration in milliseconds onto the 1-20 speed slider.

    Counter-intuitive but deliberate: a 20-second cycle is *slow*, so it maps
    to the bottom of the slider.

    Kept continuous rather than rounded to the slider's step: the panel loads
    a stored duration and must round-trip it, so snapping 8000 ms to a whole
    speed of 2 would reload it as 10000 ms.
    """
    if duration <= 0:
        return float(FALLBACK_SPEED)
    return max(SPEED_MIN, min(SPEED_MAX, DURATION_AT_UNIT_SPEED / duration))


def speed_to_duration(speed: float) -> int:
    """Map a speed-slider position back onto a duration in milliseconds."""
    return int(DURATION_AT_UNIT_SPEED / max(1, speed))


@dataclass(frozen=True)
class EffectControls:
    """Which of the lighting controls an effect makes meaningful."""

    speed: bool
    color: bool
    brightness: bool


def controls_for(mode: str) -> EffectControls:
    """An effect enables only the controls that do something.

    "Off" is special: the colour and brightness are still stored, but changing
    them while the LEDs are off has no visible result, so they are disabled to
    avoid the impression that they are broken.
    """
    lit = mode != "off"
    return EffectControls(
        speed=mode in ANIMATED_MODES,
        color=lit,
        brightness=lit,
    )


def default_mask(
    current: Sequence[bool], toggled: int, on: bool
) -> tuple[bool, ...]:
    """The default flags after the slot at `toggled` is switched on or off.

    The hardware honours exactly one default slot, so turning one on has to
    clear the others rather than leaving two. Turning one *off* leaves the rest
    alone: it must not promote an arbitrary neighbour, which would silently
    move the default the user did not ask to move.

    Taking the current mask rather than just the count keeps this well defined
    for a config that already holds two defaults, which a hand-edited file can.
    """
    mask = list(current)
    if not 0 <= toggled < len(mask):
        return tuple(mask)
    if on:
        return tuple(position == toggled for position in range(len(mask)))
    mask[toggled] = False
    return tuple(mask)



# The DPI values the track labels, so the scale can be read without hovering.
# Chosen to cover the useful range: a G502 is rarely set above 6400.
TICK_DPI: tuple[int, ...] = (100, 400, 800, 1600, 3200, 6400, 25600)

# The step a dragged marker lands on. Fine enough to reach any value a user
# would type, coarse enough that a drag does not produce 1237.
DPI_STEP = 50


def snap_dpi(dpi: float) -> int:
    """Round a DPI to the nearest step, inside the range the mouse accepts."""
    stepped = round(dpi / DPI_STEP) * DPI_STEP
    return int(max(100, min(25600, stepped)))
