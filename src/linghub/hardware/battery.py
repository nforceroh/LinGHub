"""The mouse's battery, read from the kernel's hidpp power-supply device.

A wireless G502 appears in `/sys/class/power_supply/` as `hidpp_battery_N`, with
`capacity`, `status` and `model_name`. This is a kernel driver, so no HID++ work
is needed — but ratbagd does not expose battery at all, so it is a read path of
our own.

A wired mouse has no such device. That is not an error: it is a mouse with no
battery to report, and `battery()` returns None rather than raising.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

POWER_SUPPLY = Path("/sys/class/power_supply")

# The kernel names these hidpp_battery_N.
_PREFIX = "hidpp_battery"


@dataclass(frozen=True)
class Battery:
    """What the kernel reports about the mouse's charge."""

    capacity: int
    charging: bool

    @property
    def label(self) -> str:
        return f"{self.capacity}%"


def _read(path: Path, name: str) -> str | None:
    try:
        return path.joinpath(name).read_text(encoding="utf-8").strip()
    except OSError:
        return None


def model_name(power_supply: Path = POWER_SUPPLY) -> str | None:
    """The device name the kernel reports, if it reports one.

    Read from the same power-supply entry as the charge, so a wired mouse — which
    has no such entry — returns None and the caller falls back to what ratbagd
    knows.
    """
    try:
        entries = sorted(power_supply.iterdir())
    except OSError:
        return None
    for entry in entries:
        if not entry.name.startswith(_PREFIX):
            continue
        name = _read(entry, "model_name")
        if name:
            return name
    return None


def battery(power_supply: Path = POWER_SUPPLY) -> Battery | None:
    """The mouse's battery, or None if it has none.

    None covers both a wired mouse and a kernel that does not expose the device,
    because the caller shows the same thing for both: no battery line.
    """
    try:
        entries = sorted(power_supply.iterdir())
    except OSError:
        return None

    for entry in entries:
        if not entry.name.startswith(_PREFIX):
            continue
        raw = _read(entry, "capacity")
        if raw is None:
            continue
        try:
            capacity = int(raw)
        except ValueError:
            continue
        status = (_read(entry, "status") or "").lower()
        return Battery(capacity=capacity, charging=status == "charging")
    return None