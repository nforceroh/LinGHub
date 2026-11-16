"""The daemon's decision logic, independent of D-Bus and the clock.

The daemon holds a stack of active games. A game starting pushes onto the
stack; a game exiting pops it. The profile to load is the top of the stack,
or the desktop profile when the stack is empty. This handles nested
registrations (launcher then game) without special cases.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from ..config import Config
from ..discovery.detector import Detection
from ..domain.profile import Binding, Profile


def fingerprint(profile: Profile) -> str:
    """A stable digest of everything that affects what gets written.

    Used to notice that a profile's contents changed even though its name did
    not. Bindings are sorted so dict ordering cannot cause a spurious rewrite.
    """
    import hashlib
    import json

    payload = {
        "report_rate": profile.report_rate,
        "resolutions": list(profile.resolutions),
        "bindings": {
            str(index): [binding.type, binding.value]
            for index, binding in sorted(profile.bindings.items())
        },
        "leds": list(profile.leds),
    }
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass
class DaemonState:
    """What the daemon currently believes, and what it should do next."""

    config: Config
    stack: list[str] = field(default_factory=list)
    loaded_profile: str | None = None
    loaded_fingerprint: str | None = None

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
        """True when the target differs from what is loaded.

        Compares a fingerprint rather than just the name, so editing a
        profile's bindings in the config causes a rewrite even though the
        profile is still called the same thing.
        """
        target = self.target_profile
        return (
            self.loaded_profile != target.name
            or self.loaded_fingerprint != fingerprint(target)
        )

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
        profile = self.config.profile_named(profile_name)
        self.loaded_fingerprint = fingerprint(profile) if profile else None

    def set_binding(
        self, profile_name: str, index: int, binding: Binding | None
    ) -> bool:
        """Change one button's binding in the running config.

        Applied to a copy that replaces the old config in one step, so a
        failed save cannot leave the config half-edited. The loaded
        fingerprint is deliberately left alone, which makes `needs_write`
        true and gets the daemon to push the change to the mouse.

        Returns False when the profile does not exist, so the UI can tell a
        typo from a write that is genuinely queued.
        """
        profile = self.config.profile_named(profile_name)
        if profile is None:
            return False

        self._replace_profile(profile_name, profile.with_binding(index, binding))
        return True

    def set_leds(self, profile_name: str, settings: dict) -> bool:
        """Set every LED zone of a profile to the same effect.

        Like set_binding, the loaded fingerprint is left alone so the daemon
        pushes the change to the mouse on its next tick.
        """
        profile = self.config.profile_named(profile_name)
        if profile is None:
            return False
        self._replace_profile(profile_name, profile.with_leds(settings))
        return True

    def set_resolution(
        self, profile_name: str, index: int, dpi: int, *,
        make_default: bool = False, disabled: bool | None = None,
    ) -> bool:
        """Change one DPI slot.

        Only one slot may be the default: ratbagd honours a single one, so
        moving the marker has to clear the old one rather than leaving two.
        """
        profile = self.config.profile_named(profile_name)
        if profile is None:
            return False
        if not 0 <= index < len(profile.resolutions):
            return False

        updated = []
        for position, resolution in enumerate(profile.resolutions):
            if position != index:
                entry = dict(resolution)
                if make_default:
                    entry.pop("default", None)
                updated.append(entry)
                continue

            entry = dict(resolution)
            entry["dpi"] = int(dpi)
            if make_default:
                entry["default"] = True
            if disabled is not None:
                entry["disabled"] = bool(disabled)
            updated.append(entry)

        self._replace_profile(
            profile_name, replace(profile, resolutions=tuple(updated))
        )
        return True

    def set_report_rate(self, profile_name: str, rate: int) -> bool:
        profile = self.config.profile_named(profile_name)
        if profile is None:
            return False
        self._replace_profile(profile_name, replace(profile, report_rate=int(rate)))
        return True

    def _replace_profile(self, profile_name: str, updated: Profile) -> None:
        self.config = replace(
            self.config,
            profiles=[
                updated if candidate.name == profile_name else candidate
                for candidate in self.config.profiles
            ],
        )
