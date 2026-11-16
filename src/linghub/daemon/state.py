"""The daemon's decision logic, independent of D-Bus and the clock.

The daemon holds a stack of active games. A game starting pushes onto the
stack; a game exiting pops it. The profile to load is the top of the stack,
or the desktop profile when the stack is empty. This handles nested
registrations (launcher then game) without special cases.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import Config
from ..discovery.detector import Detection
from ..domain.profile import Profile


@dataclass
class DaemonState:
    """What the daemon currently believes, and what it should do next."""

    config: Config
    stack: list[str] = field(default_factory=list)
    loaded_profile: str | None = None

    @property
    def target_profile(self) -> Profile:
        """The profile that should be loaded right now."""
        if self.stack:
            profile = self.config.profile_named(self.stack[-1])
            if profile is not None:
                return profile
        desktop = self.config.desktop
        if desktop is None:
            raise RuntimeError(f"desktop profile {self.config.desktop_profile!r} is missing")
        return desktop

    @property
    def needs_write(self) -> bool:
        return self.loaded_profile != self.target_profile.name

    def observe(self, detection: Detection) -> None:
        """Update the stack from one detection pass.

        Every running game is pushed, in detection order, so nested
        registrations stack correctly. A game that is no longer running is
        removed wherever it sits in the stack, so a game exiting out of order
        cannot strand the stack.
        """
        running = {match.profile.name for match in detection.matches}

        self.stack = [name for name in self.stack if name in running]

        for match in detection.matches:
            if match.profile.name not in self.stack:
                self.stack.append(match.profile.name)

    def mark_loaded(self, profile_name: str) -> None:
        self.loaded_profile = profile_name
