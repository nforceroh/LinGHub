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
        get_leds=None,
        on_set_leds=None,
        get_resolutions=None,
        get_report_rate=None,
        get_report_rates=None,
        on_set_resolution=None,
        on_set_report_rate=None,
        on_create_profile=None,
        on_rename_profile=None,
        on_delete_profile=None,
    ):
        super().__init__(INTERFACE)
        self._on_load_profile = on_load_profile
        self._on_reload = on_reload
        self._get_state = get_state
        self._get_bindings = get_bindings
        self._on_set_binding = on_set_binding
        self._get_leds = get_leds
        self._on_set_leds = on_set_leds
        self._get_resolutions = get_resolutions
        self._get_report_rate = get_report_rate
        self._get_report_rates = get_report_rates
        self._on_set_resolution = on_set_resolution
        self._on_set_report_rate = on_set_report_rate
        self._on_create_profile = on_create_profile
        self._on_rename_profile = on_rename_profile
        self._on_delete_profile = on_delete_profile

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

    @method()
    def CreateProfile(self, name: "s", executable: "s") -> "b":
        """Add a profile, optionally bound to a game executable.

        An empty executable makes a desktop-style profile: one that is never
        matched to a game.
        """
        if self._on_create_profile is None:
            return False
        logger.info("CreateProfile(%r, %r) requested over D-Bus", name, executable)
        return bool(self._on_create_profile(name, executable))

    @method()
    def RenameProfile(self, old: "s", new: "s") -> "b":
        """Rename a profile and every reference to it."""
        if self._on_rename_profile is None:
            return False
        logger.info("RenameProfile(%r, %r) requested over D-Bus", old, new)
        return bool(self._on_rename_profile(old, new))

    @method()
    def DeleteProfile(self, name: "s") -> "b":
        """Remove a profile. Refused for the desktop profile."""
        if self._on_delete_profile is None:
            return False
        logger.info("DeleteProfile(%r) requested over D-Bus", name)
        return bool(self._on_delete_profile(name))

    @method()
    def GetResolutions(self, profile: "s") -> "a(uuuu)":
        """A profile's DPI slots as (index, dpi, is_default, is_disabled).

        The flags are 0/1 rather than D-Bus booleans: dbus-fast rejects `bool`
        inside a struct when the value came from a Python int, and the caller
        only needs to know whether each is set.
        """
        if self._get_resolutions is None:
            return []
        slots = self._get_resolutions(profile) or ()
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
    def SetResolution(
        self, profile: "s", index: "i", dpi: "u", make_default: "b", disabled: "b"
    ) -> "b":
        """Change one DPI slot."""
        if self._on_set_resolution is None:
            return False
        logger.info(
            "SetResolution(%r, %d, dpi=%d, default=%s, disabled=%s) requested over D-Bus",
            profile, index, dpi, make_default, disabled,
        )
        return bool(self._on_set_resolution(profile, index, dpi, make_default, disabled))

    @method()
    def GetReportRate(self, profile: "s") -> "u":
        """The profile's report rate in Hz, or 0 if unset."""
        if self._get_report_rate is None:
            return 0
        return int(self._get_report_rate(profile) or 0)

    @method()
    def GetReportRates(self, profile: "s") -> "au":
        """The report rates the device accepts, in Hz.

        Read from hardware rather than hard-coded, so a device that offers a
        different set is not presented with the wrong choices.
        """
        if self._get_report_rates is None:
            return []
        return [int(rate) for rate in (self._get_report_rates(profile) or ())]

    @method()
    def SetReportRate(self, profile: "s", rate: "u") -> "b":
        """Change the profile's report rate."""
        if self._on_set_report_rate is None:
            return False
        logger.info("SetReportRate(%r, %d) requested over D-Bus", profile, rate)
        return bool(self._on_set_report_rate(profile, rate))

    @method()
    def GetLeds(self, profile: "s") -> "a(us(uuu)uu)":
        """A profile's LED settings, one entry per zone.

        Returns (index, mode, colour, brightness, duration). The zones are
        separate in the hardware even when the UI drives them together, so the
        shape stays honest about that.
        """
        if self._get_leds is None:
            return []
        leds = self._get_leds(profile) or {}
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
        if self._on_set_leds is None:
            return False
        logger.info(
            "SetLeds(%r, %r, brightness=%d, duration=%d, rgb=(%d,%d,%d)) requested over D-Bus",
            profile, mode, brightness, duration, red, green, blue,
        )
        return bool(self._on_set_leds(profile, {
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
