"""The daemon's D-Bus interface on the session bus.

The UI talks to the daemon through this, so there is one writer for the
config and one owner of "which profile is loaded". Methods that change state
are routed through the daemon rather than editing the config file directly.

The interface is deliberately small: read what is happening, ask for a
profile, and get told when something changes.
"""

from __future__ import annotations

import logging

from dbus_fast.service import (
    PropertyAccess,
    ServiceInterface,
    dbus_property,
    method,
    signal,
)


SERVICE = "org.linghub.Manager"
PATH = "/org/linghub/Manager"
INTERFACE = "org.linghub.Manager"

logger = logging.getLogger("linghub.dbus")


class ManagerInterface(ServiceInterface):
    """Exposes daemon state and control over the session bus.

    The daemon owns the state; this class only translates between D-Bus and
    the callbacks it is given, so it can be tested without a bus.
    """

    def __init__(
        self,
        on_load_profile,
        on_reload,
        get_state,
        get_bindings=None,
        on_set_binding=None,
    ):
        super().__init__(INTERFACE)
        self._on_load_profile = on_load_profile
        self._on_reload = on_reload
        self._get_state = get_state
        self._get_bindings = get_bindings
        self._on_set_binding = on_set_binding

    @method()
    def LoadProfile(self, name: "s") -> "b":
        """Load a named profile now, overriding game detection until it changes."""
        logger.info("LoadProfile(%r) requested over D-Bus", name)
        return bool(self._on_load_profile(name))

    @method()
    def Reload(self) -> "b":
        """Re-read the config file from disk."""
        logger.info("Reload requested over D-Bus")
        return bool(self._on_reload())

    @method()
    def ListProfiles(self) -> "as":
        """Every profile name in the config."""
        return list(self._get_state().profile_names)

    @method()
    def GetBindings(self, profile: "s") -> "a(iss)":
        """Every binding in a profile, as (button index, type, value).

        Returned as a flat list rather than a dict because D-Bus has no
        integer-keyed map, and the value's type depends on the binding type,
        so it is always a string here and decoded by the caller.
        """
        if self._get_bindings is None:
            return []
        bindings = self._get_bindings(profile) or {}
        return [
            (int(index), str(kind), "" if value is None else str(value))
            for index, (kind, value) in sorted(bindings.items())
        ]

    @method()
    def SetBinding(self, profile: "s", index: "i", kind: "s", value: "s") -> "b":
        """Assign one button's binding and write it to the config.

        The daemon is the single writer (ADR-0004), so the UI edits through
        here rather than touching the file.
        """
        if self._on_set_binding is None:
            return False
        logger.info(
            "SetBinding(%r, %d, %r, %r) requested over D-Bus", profile, index, kind, value
        )
        return bool(self._on_set_binding(profile, index, kind, value or None))

    @method()
    def ClearBinding(self, profile: "s", index: "i") -> "b":
        """Remove a button's binding.

        Recorded as `disabled` rather than an empty mapping: ADR-0003 says
        never to write ACTION_NONE, which corrupts G502 Hero buttons.
        """
        if self._on_set_binding is None:
            return False
        logger.info("ClearBinding(%r, %d) requested over D-Bus", profile, index)
        return bool(self._on_set_binding(profile, index, "disabled", None))

    @dbus_property(access=PropertyAccess.READ)
    def ActiveProfile(self) -> "s":
        """The profile currently loaded on the mouse, or empty if unknown."""
        return self._get_state().loaded_profile or ""

    @dbus_property(access=PropertyAccess.READ)
    def DetectedGame(self) -> "s":
        """The game currently detected, or empty."""
        return self._get_state().detected_game or ""

    @dbus_property(access=PropertyAccess.READ)
    def DesktopProfile(self) -> "s":
        """The name of the profile used when no game is running."""
        return self._get_state().desktop_profile

    @signal()
    def ProfileChanged(self, name: "s") -> "s":
        """Emitted after a profile is loaded onto the mouse."""
        return name

    @signal()
    def GameDetected(self, name: "s") -> "s":
        """Emitted when a game starts being detected."""
        return name

    @signal()
    def GameExited(self, name: "s") -> "s":
        """Emitted when a detected game stops running."""
        return name
