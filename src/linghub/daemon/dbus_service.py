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

    def __init__(self, profiles, bindings, settings, get_view):
        """Take the three collaborators the methods act on, plus one reader.

        Grouping by what each method acts on keeps the interface small: adding
        a member means adding it to one collaborator, not to a fifteen-argument
        constructor. Every read goes through `get_view(profile)`, which
        returns a `snapshot.View`; this class only turns it into D-Bus types.
        """
        super().__init__(INTERFACE)
        self._profiles = profiles
        self._bindings = bindings
        self._settings = settings
        self._get_view = get_view

    def _state(self):
        return self._get_view("").state

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
        return list(self._state().profile_names)

    @method()
    def GetView(self, profile: "s") -> "(sssasa(iss)a(us(uuu)uu)a(uuuu)auu)":
        """Everything a client shows, in one read.

        Returns (active profile, detected game, desktop profile, profile
        names; then the named profile's bindings, LEDs, DPI slots, accepted
        report rates, and its current report rate). An unknown profile yields
        empty sections rather than an error: the UI may ask about a profile
        that has just been deleted, and "nothing there yet" is the answer it
        wants, not a failure.

        One read replaces the five per-section members the client used to
        call in sequence, so a refresh costs one round trip and a partial read
        cannot leave the UI showing a state pieced together from two ticks.
        """
        view = self._get_view(profile)
        state, sections = view.state, view.profile
        return (
            state.loaded_profile or "",
            state.detected_game or "",
            state.desktop_profile,
            list(state.profile_names),
            [
                (int(index), str(kind), "" if value is None else str(value))
                for index, kind, value in sections.bindings
            ],
            [_marshal_led(settings) for settings in sections.leds],
            [
                (index, int(dpi), 1 if default else 0, 1 if disabled else 0)
                for index, (dpi, default, disabled) in enumerate(sections.resolutions)
            ],
            [int(rate) for rate in sections.report_rates],
            int(sections.report_rate),
        )

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
        return self._state().loaded_profile or ""

    @dbus_property(access=PropertyAccess.READ)
    def DetectedGame(self) -> "s":
        """The game currently detected, or empty."""
        return self._state().detected_game or ""

    @dbus_property(access=PropertyAccess.READ)
    def DesktopProfile(self) -> "s":
        """The name of the profile used when no game is running."""
        return self._state().desktop_profile

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

    @signal()
    def ConfigChanged(self) -> None:
        """Emitted after the config changes: an edit, or the file reloaded."""
        return None


def _marshal_led(settings: dict) -> tuple:
    """One LED zone as (index, mode, colour, brightness, duration)."""
    color = settings.get("color") or (0, 0, 0)
    return (
        int(settings["index"]),
        str(settings.get("mode", "off")),
        (int(color[0]), int(color[1]), int(color[2])),
        int(settings.get("brightness", 255)),
        int(settings.get("duration", 0)),
    )


class BusAnnouncer:
    """Announces the daemon's events as signals on the published interface.

    The production adapter for the daemon's announcer. Silent until the
    interface is attached: the daemon starts ticking before, or without, a
    session bus, and has nobody to tell.
    """

    def __init__(self):
        self._interface: ManagerInterface | None = None

    def attach(self, interface: ManagerInterface) -> None:
        self._interface = interface

    def profile_loaded(self, name: str) -> None:
        if self._interface is not None:
            self._interface.ProfileChanged(name)

    def game_started(self, name: str) -> None:
        if self._interface is not None:
            self._interface.GameDetected(name)

    def game_stopped(self, name: str) -> None:
        if self._interface is not None:
            self._interface.GameExited(name)

    def config_changed(self) -> None:
        if self._interface is not None:
            self._interface.ConfigChanged()
