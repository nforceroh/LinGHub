"""A read-only view of daemon state for the D-Bus interface.

Keeping this separate from DaemonState means the interface cannot mutate the
daemon's internals, and it can be constructed in tests without a daemon.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StateSnapshot:
    profile_names: tuple[str, ...] = ()
    loaded_profile: str | None = None
    detected_game: str | None = None
    desktop_profile: str = "desktop"
