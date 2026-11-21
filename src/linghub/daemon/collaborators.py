"""The three things the D-Bus adapter needs from the daemon.

The adapter used to take fifteen callbacks, one per method, and forward each
one. That made its interface as wide as its implementation: adding a member
meant editing the constructor, the assignment block, the method, and every
test's fake.

The methods fall into three groups by what they act on, so the adapter takes
three collaborators instead. Each is a Protocol, so the daemon does not have to
inherit anything and a test can pass a plain object.

The Protocols are load-bearing: `writes.py` implements them and
`tests/test_collaborators.py` checks the implementations against them by
comparing signatures. `runtime_checkable` alone would only compare method
names, so a drifted parameter list would pass unnoticed.

Delete a Protocol and the D-Bus adapter loses its statement of what it needs;
delete an implementation and the daemon has nothing to call. Neither is a
comment with a syntax cost.
"""

from __future__ import annotations

from typing import Protocol


class ProfileLifecycle(Protocol):
    """Which profile is loaded, and the set of profiles that exist."""

    def load(self, name: str) -> bool:
        """Load a profile now, overriding detection until it changes."""

    def reload(self) -> bool:
        """Re-read the config file."""

    def create(self, name: str, executable: str) -> bool:
        """Add a profile, optionally bound to a game executable."""

    def rename(self, old: str, new: str) -> bool:
        """Rename a profile and every reference to it."""

    def delete(self, name: str) -> bool:
        """Remove a profile. Refused for the desktop one."""

    def duplicate(self, name: str, new: str) -> bool:
        """Add `new` as a full copy of `name`, including its games."""

    def rename_game(self, profile: str, executable: str, name: str) -> bool:
        """Set one game's display name."""


class Bindings(Protocol):
    """What each button does in a profile."""

    def set(self, profile: str, index: int, kind: str, value: object) -> bool:
        """Assign one button's binding."""

    def clear(self, profile: str, index: int) -> bool:
        """Record a button as doing nothing."""


class DeviceSettings(Protocol):
    """DPI, report rate and lighting for a profile."""

    def set_resolution(
        self, profile: str, index: int, dpi: int,
        make_default: bool, disabled: bool,
    ) -> bool:
        """Change one DPI slot."""

    def set_report_rate(self, profile: str, rate: int) -> bool:
        """Change the report rate."""

    def set_leds(self, profile: str, settings: dict) -> bool:
        """Set every LED zone to one effect."""
