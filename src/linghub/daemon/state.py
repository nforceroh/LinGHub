"""The daemon's decision logic, independent of D-Bus and the clock.

The daemon holds a stack of active games. A game starting pushes onto the
stack; a game exiting pops it. The top of the stack is the current game. This
handles nested registrations (launcher then game) without special cases.

The profile to load is the manual override if there is one, else the current
game's profile, else the desktop profile. Every name those three depend on
lives here, so renaming or deleting a profile can update all of them at once.

A manual override holds until the current game changes, whether or not a game
is running when it is made. An earlier version also dropped an override made
with no game running; that made Load at the desktop silently do nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from ..config import Config
from ..discovery.detector import Detection
from ..domain.profile import Binding, Game, Profile
from . import slots


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


@dataclass(frozen=True)
class GameChange:
    """The current game changed during one detection pass."""

    # The game that is now current, if any.
    started: str | None
    # The game that was current before, if any.
    stopped: str | None


@dataclass
class DaemonState:
    """What the daemon currently believes, and what it should do next."""

    config: Config
    stack: list[str] = field(default_factory=list)
    loaded_profile: str | None = None
    loaded_fingerprint: str | None = None
    _slot_drifted: bool = False
    _manual_override: str | None = None

    @property
    def manual_override(self) -> str | None:
        """The profile loaded by hand, or None when detection decides."""
        return self._manual_override

    def request(self, name: str) -> bool:
        """Load a profile by hand, overriding detection until the game changes.

        A name that is not in the config is refused rather than held: it
        could never be loaded.
        """
        if self.config.profile_named(name) is None:
            return False
        self._manual_override = name
        return True

    @property
    def target_profile(self) -> Profile:
        """The profile that should be loaded right now."""
        if self._manual_override is not None:
            profile = self.config.profile_named(self._manual_override)
            if profile is not None:
                return profile
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

        Also true when the hardware's active slot disagrees with what this
        state believes, which is how a physical profile button, ratbagctl, or
        a KVM reconnect gets corrected.
        """
        target = self.target_profile
        return (
            self.loaded_profile != target.name
            or self.loaded_fingerprint != fingerprint(target)
            or self._slot_drifted
        )

    def observe_active_slot(self, active_slot: int | None) -> None:
        """Record which slot the hardware says is active.

        Called each tick with the slot read from the device. The Slot rules
        themselves live in `slots`: this only holds the answer.
        """
        self._slot_drifted = slots.drifted(self.loaded, active_slot)

    @property
    def loaded(self) -> Profile | None:
        """The profile the daemon last loaded, or None if it has not loaded one."""
        if self.loaded_profile is None:
            return None
        return self.config.profile_named(self.loaded_profile)

    @property
    def expected_slot(self) -> int | None:
        """The slot the loaded profile should occupy, or None if unknown."""
        loaded = self.loaded
        return None if loaded is None else slots.slot_for(loaded)

    def observe(self, detection: Detection) -> GameChange | None:
        """Update the stack from one detection pass.

        Every running game is pushed, in detection order, so nested
        registrations stack correctly. A game that is no longer running is
        removed wherever it sits in the stack, so a game exiting out of order
        cannot strand the stack.

        When the current game changes, a manual override ends and the change
        is returned so the daemon can announce it. Otherwise returns None.
        """
        previous = self.current_game
        running = {match.profile.name for match in detection.matches}

        self.stack = [name for name in self.stack if name in running]

        for match in detection.matches:
            if match.profile.name not in self.stack:
                self.stack.append(match.profile.name)

        if self.current_game == previous:
            return None
        self._manual_override = None
        return GameChange(started=self.current_game, stopped=previous)

    @property
    def current_game(self) -> str | None:
        """The most recently started game still running, or None."""
        return self.stack[-1] if self.stack else None

    def mark_loaded(self, profile_name: str) -> None:
        self.loaded_profile = profile_name
        profile = self.config.profile_named(profile_name)
        self.loaded_fingerprint = fingerprint(profile) if profile else None
        # A successful write puts the hardware where we expect it.
        self._slot_drifted = False

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

    def create_profile(self, name: str, executable: str = "") -> bool:
        """Add a profile, optionally bound to a game executable."""
        name = name.strip()
        if not name or self.config.profile_named(name) is not None:
            return False
        games = (Game(executable),) if executable.strip() else ()
        self.config = replace(
            self.config,
            profiles=[*self.config.profiles, Profile(name=name, games=games)],
        )
        return True

    def rename_profile(self, old: str, new: str) -> bool:
        """Rename a profile and every reference to it.

        The desktop pointer, the loaded profile name and the game stack all
        hold profile names; leaving any of them stale would either lose the
        desktop profile or make the daemon rewrite the wrong slot.
        """
        new = new.strip()
        if not new or old == new:
            return False
        profile = self.config.profile_named(old)
        if profile is None or self.config.profile_named(new) is not None:
            return False

        renamed = replace(profile, name=new)
        desktop = new if self.config.desktop_profile == old else self.config.desktop_profile
        self.config = replace(
            self.config,
            profiles=[renamed if p.name == old else p for p in self.config.profiles],
            desktop_profile=desktop,
        )

        if self.loaded_profile == old:
            self.loaded_profile = new
        self.stack = [new if name == old else name for name in self.stack]
        if self._manual_override == old:
            self._manual_override = new
        return True

    def delete_profile(self, name: str) -> bool:
        """Remove a profile, unless it is the desktop one or the only one."""
        if name == self.config.desktop_profile:
            return False
        if self.config.profile_named(name) is None:
            return False
        remaining = [p for p in self.config.profiles if p.name != name]
        if not remaining:
            return False

        self.config = replace(self.config, profiles=remaining)
        self.stack = [entry for entry in self.stack if entry != name]
        if self._manual_override == name:
            self._manual_override = None
        if self.loaded_profile == name:
            self.loaded_profile = None
            self.loaded_fingerprint = None
        return True

    def _replace_profile(self, profile_name: str, updated: Profile) -> None:
        self.config = replace(
            self.config,
            profiles=[
                updated if candidate.name == profile_name else candidate
                for candidate in self.config.profiles
            ],
        )
