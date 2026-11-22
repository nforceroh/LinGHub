"""Every change to the config, and the one rule that persists it.

These are the three collaborators the D-Bus adapter calls: profile lifecycle,
bindings, and device settings. They are where the config is actually edited —
validation, persistence and rollback all happen here — which leaves the daemon
with the run loop, the device connection, detection, and pushing a profile to
the mouse.

The classes used to be three shells that forwarded fifteen calls into a
49-method `Daemon`, so the interface had shrunk while the complexity stayed
put. The methods moved here; the names alone did not.

Nothing in this module knows about slots, ticks, or D-Bus. It takes a way to
read the current state, a way to persist it, and a way to ask for a redraw.
The collaborators only change things: every read goes through
`snapshot.read_view`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from .. import config as config_module
from ..domain.profile import Binding
from ..hardware import mapping
from .state import DaemonState

logger = logging.getLogger("linghub.writes")


StateProvider = Callable[[], DaemonState | None]


class ConfigWrites:
    """The one rule every config change obeys: change, save, roll back.

    The running config must never disagree with the file, so a change that
    cannot be persisted is undone. Having a single owner of that rule is the
    point: a new write path cannot forget the rollback, because it cannot
    reach the config without going through `apply`.
    """

    def __init__(
        self,
        state: StateProvider,
        save: Callable[[], bool],
        wake: Callable[[], None],
        announce: Callable[[], None],
    ):
        self._state = state
        self._save = save
        self._wake = wake
        self._announce = announce

    def apply(self, change: Callable[[DaemonState], bool], description: str) -> bool:
        """Run `change`, persist it, and restore the old config if saving fails.

        `change` receives the state rather than closing over it, so the rule
        can be exercised against a state the caller chose.
        """
        state = self._state()
        if state is None:
            logger.warning("%s: the daemon has no config yet", description)
            return False

        previous = state.config
        if not change(state):
            logger.warning("%s: rejected", description)
            return False
        if not self._save():
            state.config = previous
            return False
        logger.info("%s applied", description)
        # The change is only in the config and the file until the next tick
        # pushes it at the mouse, so ask for that tick now.
        self._wake()
        # Clients show the profile list and the panels from the config, so
        # they need to hear about the change; the tick only announces loads.
        self._announce()
        return True


class ProfileLifecycle:
    """Which profiles exist, and which one is loaded."""

    def __init__(
        self,
        state: StateProvider,
        writes: ConfigWrites,
        request_load: Callable[[str], bool],
        request_reload: Callable[[], bool],
    ):
        self._state = state
        self._writes = writes
        self._request_load = request_load
        self._request_reload = request_reload

    def load(self, name: str) -> bool:
        """Load a profile now, overriding detection until that changes.

        A name that is not in the config is refused rather than queued: the
        caller expects to learn that its request was wrong, and a queued bad
        name would only fail again on the next tick.
        """
        state = self._state()
        if state is None or state.config.profile_named(name) is None:
            logger.warning("LoadProfile(%r): no such profile", name)
            return False
        return self._request_load(name)

    def reload(self) -> bool:
        """Re-read the config file from disk."""
        return self._request_reload()

    def create(self, name: str, executable: str) -> bool:
        return self._writes.apply(
            lambda state: state.create_profile(name, executable),
            f"CreateProfile({name!r})",
        )

    def rename(self, old: str, new: str) -> bool:
        return self._writes.apply(
            lambda state: state.rename_profile(old, new),
            f"RenameProfile({old!r}, {new!r})",
        )

    def duplicate(self, name: str, new: str) -> bool:
        return self._writes.apply(
            lambda state: state.duplicate_profile(name, new),
            f"DuplicateProfile({name!r}, {new!r})",
        )

    def rename_game(self, profile: str, executable: str, name: str) -> bool:
        return self._writes.apply(
            lambda state: state.rename_game(profile, executable, name),
            f"RenameGame({profile!r}, {executable!r})",
        )

    def delete(self, name: str) -> bool:
        return self._writes.apply(
            lambda state: state.delete_profile(name),
            f"DeleteProfile({name!r})",
        )


class Bindings:
    """What each button does in a profile."""

    def __init__(self, writes: ConfigWrites):
        self._writes = writes

    def set(self, profile: str, index: int, kind: str, value: object) -> bool:
        """Assign one button's binding, persist it, and let the next tick push it."""
        # Validate before touching the config, so a rejected value cannot leave
        # a half-edited profile behind for the rollback to have to undo.
        if kind not in Binding.VALID_TYPES:
            logger.warning("SetBinding: unknown binding type %r", kind)
            return False
        try:
            binding = Binding(type=kind, value=value)
            # Saved, an unencodable binding would only fail at write time (#8).
            mapping.encode(binding)
        except ValueError as exc:
            logger.warning("SetBinding: %s", exc)
            return False

        return self._writes.apply(
            lambda state: state.set_binding(profile, index, binding),
            f"SetBinding({profile!r}, {index}, {kind}, {value!r})",
        )

    def clear(self, profile: str, index: int) -> bool:
        """Record a button as doing nothing.

        Recorded as `disabled` rather than an empty mapping: ADR-0003 says never
        to write ACTION_NONE, which corrupts G502 Hero buttons.
        """
        return self.set(profile, index, "disabled", None)


class DeviceSettings:
    """DPI, report rate and lighting for a profile."""

    def __init__(self, writes: ConfigWrites):
        self._writes = writes

    def set_resolution(
        self, profile: str, index: int, dpi: int,
        make_default: bool, disabled: bool,
    ) -> bool:
        return self._writes.apply(
            lambda state: state.set_resolution(
                profile, index, dpi,
                make_default=make_default, disabled=disabled,
            ),
            f"SetResolution({profile!r}, {index}, {dpi})",
        )

    def set_report_rate(self, profile: str, rate: int) -> bool:
        return self._writes.apply(
            lambda state: state.set_report_rate(profile, rate),
            f"SetReportRate({profile!r}, {rate})",
        )

    def set_leds(self, profile: str, settings: dict) -> bool:
        """Set every LED zone of a profile to one effect."""
        try:
            # Reuse the config validator so the ranges cannot drift from what
            # a hand-written file is allowed to contain.
            config_module.validate_led(dict(settings, index=0))
        except config_module.ConfigError as exc:
            logger.warning("SetLeds: %s", exc)
            return False

        return self._writes.apply(
            lambda state: state.set_leds(profile, settings),
            f"SetLeds({profile!r}, {settings!r})",
        )


@dataclass(frozen=True)
class Collaborators:
    """The three things the D-Bus adapter calls, sharing one write rule."""

    profiles: ProfileLifecycle
    bindings: Bindings
    settings: DeviceSettings


def build_collaborators(
    state: StateProvider,
    save: Callable[[], bool],
    wake: Callable[[], None],
    announce: Callable[[], None],
    request_load: Callable[[str], bool],
    request_reload: Callable[[], bool],
) -> Collaborators:
    """Wire the collaborators to one ConfigWrites.

    The daemon and the tests build them the same way, so a new dependency is
    added here once rather than in every place that wires them.
    """
    writes = ConfigWrites(state=state, save=save, wake=wake, announce=announce)
    return Collaborators(
        profiles=ProfileLifecycle(
            state=state,
            writes=writes,
            request_load=request_load,
            request_reload=request_reload,
        ),
        bindings=Bindings(writes),
        settings=DeviceSettings(writes),
    )
