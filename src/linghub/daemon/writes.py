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
"""

from __future__ import annotations

import logging
from typing import Callable

from .. import config as config_module
from ..domain.profile import Binding
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


class _Reader:
    """Shared plumbing for the collaborators' read paths."""

    def __init__(self, state: StateProvider):
        self._state = state

    def _profile(self, name: str):
        state = self._state()
        if state is None:
            return None
        return state.config.profile_named(name)


class ProfileLifecycle(_Reader):
    """Which profiles exist, and which one is loaded."""

    def __init__(
        self,
        state: StateProvider,
        writes: ConfigWrites,
        request_load: Callable[[str], bool],
        request_reload: Callable[[], bool],
    ):
        super().__init__(state)
        self._writes = writes
        self._request_load = request_load
        self._request_reload = request_reload

    def load(self, name: str) -> bool:
        """Load a profile now, overriding detection until that changes.

        A name that is not in the config is refused rather than queued: the
        caller expects to learn that its request was wrong, and a queued bad
        name would only fail again on the next tick.
        """
        if self._profile(name) is None:
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

    def delete(self, name: str) -> bool:
        return self._writes.apply(
            lambda state: state.delete_profile(name),
            f"DeleteProfile({name!r})",
        )


class Bindings(_Reader):
    """What each button does in a profile."""

    def __init__(self, state: StateProvider, writes: ConfigWrites):
        super().__init__(state)
        self._writes = writes

    def get(self, profile: str) -> dict[int, tuple[str, object]]:
        """Every binding, keyed by ratbag index."""
        found = self._profile(profile)
        if found is None:
            return {}
        return {
            index: (binding.type, binding.value)
            for index, binding in found.bindings.items()
        }

    def set(self, profile: str, index: int, kind: str, value: object) -> bool:
        """Assign one button's binding, persist it, and let the next tick push it."""
        # Validate before touching the config, so a rejected value cannot leave
        # a half-edited profile behind for the rollback to have to undo.
        if kind not in Binding.VALID_TYPES:
            logger.warning("SetBinding: unknown binding type %r", kind)
            return False
        try:
            binding = Binding(type=kind, value=value)
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


class DeviceSettings(_Reader):
    """DPI, report rate and lighting for a profile."""

    def __init__(
        self,
        state: StateProvider,
        writes: ConfigWrites,
        report_rates: Callable[[], tuple[int, ...]],
    ):
        super().__init__(state)
        self._writes = writes
        self._report_rates = report_rates

    def get_resolutions(self, profile: str) -> tuple:
        """DPI slots as (dpi, is_default, is_disabled), in order."""
        found = self._profile(profile)
        if found is None:
            return ()
        return tuple(
            (
                int(slot.get("dpi", 0)),
                bool(slot.get("default")),
                bool(slot.get("disabled")),
            )
            for slot in found.resolutions
        )

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

    def get_report_rate(self, profile: str) -> int:
        """The profile's report rate in Hz, or 0 if unset."""
        found = self._profile(profile)
        return int(found.report_rate or 0) if found is not None else 0

    def get_report_rates(self, profile: str) -> tuple[int, ...]:
        """The rates the device accepts.

        Read from the device rather than hard-coded, so a variant offering a
        different set is not presented with the wrong choices.
        """
        return tuple(self._report_rates())

    def set_report_rate(self, profile: str, rate: int) -> bool:
        return self._writes.apply(
            lambda state: state.set_report_rate(profile, rate),
            f"SetReportRate({profile!r}, {rate})",
        )

    def get_leds(self, profile: str) -> dict[int, dict]:
        """A profile's LED zones, keyed by index."""
        found = self._profile(profile)
        if found is None:
            return {}
        return {int(entry["index"]): dict(entry) for entry in found.leds}

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