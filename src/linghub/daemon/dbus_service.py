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


from ..dbus_contract import INTERFACE, PATH, SERVICE

logger = logging.getLogger("linghub.dbus")


class ManagerInterface(ServiceInterface):
    """Exposes daemon state and control over the session bus.

    The daemon owns the state; this class only translates between D-Bus and
    the callbacks it is given, so it can be tested without a bus.
    """

    def __init__(self, profiles, bindings, settings, get_state):
        """Take the three collaborators the methods act on, plus a state reader.

        Grouping by what each method acts on keeps the interface small: adding
        a member means adding it to one collaborator, not to a fifteen-argument
        constructor.
        """
        super().__init__(INTERFACE)
        self._profiles = profiles
        self._bindings = bindings
        self._settings = settings
        self._get_state = get_state

    @method()
    def LoadProfile(self, name: "s") -> "b":
        """Load a named profile now, overriding game detection until it changes."""
        logger.info("LoadProfile(%r) requested over D-Bus", name)
        return bool(self._profiles.load(name))

    @method()
    def Reload(self) -> "b":
        """Re-read the config file from disk."""
        logger.info("Reload requested over D-Bus")
        return bool(self._profiles.reload())

    @method()
    def ListProfiles(self) -> "as":
        """Every profile name in the config."""
        return list(self._get_state().profile_names)

    @method()
    def GetView(self, profile: "s") -> "(sssasa(iss)a(us(uuu)uu)a(uuuu)auu)":
        """Everything a UI poll needs, in one read.

        Returns (active profile, detected game, desktop profile, profile
        names; then the named profile's bindings, LEDs, DPI slots, accepted
        report rates, and its current report rate). An unknown profile yields
        empty sections rather than an error: the UI may ask about a profile
        that has just been deleted, and "nothing there yet" is the answer it
        wants, not a failure.

        One read replaces the five per-section members the client used to
        call in sequence, so a poll costs one round trip and a partial read
        cannot leave the UI showing a state pieced together from two ticks.
        """
        snapshot = self._get_state()
        return (
            snapshot.loaded_profile or "",
            snapshot.detected_game or "",
            snapshot.desktop_profile,
            list(snapshot.profile_names),
            self._view_bindings(profile),
            self._view_leds(profile),
            self._view_resolutions(profile),
            [int(rate) for rate in (self._settings.get_report_rates(profile) or ())],
            int(self._settings.get_report_rate(profile) or 0),
        )

    def _view_bindings(self, profile: str) -> list:
        bindings = self._bindings.get(profile) or {}
        return [
            (int(index), str(kind), "" if value is None else str(value))
            for index, (kind, value) in sorted(bindings.items())
        ]

    def _view_leds(self, profile: str) -> list:
        leds = self._settings.get_leds(profile) or {}
        result = []
        for index, settings in sorted(leds.items()):
            color = settings.get("color") or (0, 0, 0)
            result.append((
                int(index),
                str(settings.get("mode", "off")),
                (int(color[0]), int(color[1]), int(color[2])),
                int(settings.get("brightness", 255)),
                int(settings.get("duration", 0)),
            ))
        return result

    def _view_resolutions(self, profile: str) -> list:
        slots = self._settings.get_resolutions(profile) or ()
        return [
            (
                int(index),
                int(dpi),
                1 if default else 0,
                1 if disabled else 0,
            )
            for index, (dpi, default, disabled) in enumerate(slots)
        ]

    @method()
    def SetBinding(self, profile: "s", index: "i", kind: "s", value: "s") -> "b":
        """Assign one button's binding and write it to the config.

        The daemon is the single writer (ADR-0004), so the UI edits through
        here rather than touching the file.
        """
        logger.info(
            "SetBinding(%r, %d, %r, %r) requested over D-Bus", profile, index, kind, value
        )
        return bool(self._bindings.set(profile, index, kind, value or None))

    @method()
    def ClearBinding(self, profile: "s", index: "i") -> "b":
        """Remove a button's binding.

        Recorded as `disabled` rather than an empty mapping: ADR-0003 says
        never to write ACTION_NONE, which corrupts G502 Hero buttons.
        """
        logger.info("ClearBinding(%r, %d) requested over D-Bus", profile, index)
        return bool(self._bindings.clear(profile, index))

    @method()
    def CreateProfile(self, name: "s", executable: "s") -> "b":
        """Add a profile, optionally bound to a game executable.

        An empty executable makes a desktop-style profile: one that is never
        matched to a game.
        """
        logger.info("CreateProfile(%r, %r) requested over D-Bus", name, executable)
        return bool(self._profiles.create(name, executable))

    @method()
    def RenameProfile(self, old: "s", new: "s") -> "b":
        """Rename a profile and every reference to it."""
        logger.info("RenameProfile(%r, %r) requested over D-Bus", old, new)
        return bool(self._profiles.rename(old, new))

    @method()
    def DeleteProfile(self, name: "s") -> "b":
        """Remove a profile. Refused for the desktop profile."""
        logger.info("DeleteProfile(%r) requested over D-Bus", name)
        return bool(self._profiles.delete(name))

    @method()
    def SetResolution(
        self, profile: "s", index: "i", dpi: "u", make_default: "b", disabled: "b"
    ) -> "b":
        """Change one DPI slot."""
        logger.info(
            "SetResolution(%r, %d, dpi=%d, default=%s, disabled=%s) requested over D-Bus",
            profile, index, dpi, make_default, disabled,
        )
        return bool(self._settings.set_resolution(profile, index, dpi, make_default, disabled))

    @method()
    def SetReportRate(self, profile: "s", rate: "u") -> "b":
        """Change the profile's report rate."""
        logger.info("SetReportRate(%r, %d) requested over D-Bus", profile, rate)
        return bool(self._settings.set_report_rate(profile, rate))

    @method()
    def SetLeds(
        self,
        profile: "s",
        mode: "s",
        brightness: "u",
        duration: "u",
        red: "u",
        green: "u",
        blue: "u",
    ) -> "b":
        """Set every LED zone of a profile to the same effect.

        The UI presents the two zones as one control, so this takes one set of
        values rather than a list. Splitting them later means adding a method
        that takes a per-zone list, not changing this one's meaning.
        """
        logger.info(
            "SetLeds(%r, %r, brightness=%d, duration=%d, rgb=(%d,%d,%d)) requested over D-Bus",
            profile, mode, brightness, duration, red, green, blue,
        )
        return bool(self._settings.set_leds(profile, {
            "mode": mode,
            "brightness": brightness,
            "duration": duration,
            "color": (red, green, blue),
        }))

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
