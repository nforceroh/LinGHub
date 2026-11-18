"""Tests for the D-Bus manager interface.

The interface is a thin translation layer, so these tests check that it
routes calls to the daemon and reports state faithfully, without a bus.

The interface takes the real collaborators from `writes.py`, backed by a
fake state and save. Testing the adapter against the real collaborators
rather than fakes of them means a change to the collaborators shows up here
as a routing difference, not as a silently stale fake.
"""

import unittest

from linghub.config import Config
from linghub.daemon.dbus_service import INTERFACE, ManagerInterface
from linghub.daemon.snapshot import StateSnapshot
from linghub.daemon.state import DaemonState
from linghub.daemon.writes import (
    Bindings,
    ConfigWrites,
    DeviceSettings,
    ProfileLifecycle,
)
from linghub.domain.profile import Binding, Game, Profile


def make_config(bindings: dict | None = None, report_rate: int | None = None) -> Config:
    return Config(
        profiles=[
            Profile(name="desktop"),
            Profile(
                name="wot", games=(Game("x.exe"),),
                bindings={
                    int(index): Binding(kind, value)
                    for index, (kind, value) in (bindings or {}).items()
                },
                resolutions=({"dpi": 800}, {"dpi": 1600}),
                leds=({"index": 0, "mode": "on"},),
                report_rate=report_rate,
            ),
        ],
        desktop_profile="desktop",
        poll_interval=2.0,
    )


class FakeDaemon:
    """A state provider plus the hooks only the daemon can answer.

    The collaborators read and edit the config through it, so the adapter's
    routing is tested against the real write rule, not a copy of it.
    """

    def __init__(self, snapshot=None, accept=True, bindings=None):
        self.snapshot = snapshot or StateSnapshot()
        self.accept = accept
        self.loaded: list[str] = []
        self.reloads = 0
        self.state: DaemonState | None = DaemonState(config=make_config(bindings))

    # --- the hooks the collaborators call back into ---

    def request_load(self, name: str) -> bool:
        self.loaded.append(name)
        return self.accept

    def request_reload(self) -> bool:
        self.reloads += 1
        return True

    def save(self) -> bool:
        return self.accept

    def wake(self) -> None:
        self.woken = getattr(self, "woken", 0) + 1

    def report_rates(self) -> tuple[int, ...]:
        return (125, 250, 500, 1000)

    # --- the collaborators, built on this fake ---

    @property
    def profiles(self) -> ProfileLifecycle:
        return ProfileLifecycle(
            state=lambda: self.state,
            writes=self._writes(),
            request_load=self.request_load,
            request_reload=self.request_reload,
        )

    @property
    def bindings(self) -> Bindings:
        return Bindings(state=lambda: self.state, writes=self._writes())

    @property
    def settings(self) -> DeviceSettings:
        return DeviceSettings(
            state=lambda: self.state,
            writes=self._writes(),
            report_rates=self.report_rates,
        )

    def _writes(self) -> ConfigWrites:
        return ConfigWrites(
            state=lambda: self.state, save=self.save, wake=self.wake,
            announce=lambda: None,
        )

    def get_state(self):
        return self.snapshot


def make_interface(daemon):
    return ManagerInterface(
        profiles=daemon.profiles,
        bindings=daemon.bindings,
        settings=daemon.settings,
        get_state=daemon.get_state,
    )


def call(interface, name, *args):
    """Invoke a method's implementation.

    dbus-fast replaces the decorated attribute with a dispatcher that returns
    None, so tests reach the real function through _get_methods.
    """
    for entry in ManagerInterface._get_methods(interface):
        if entry.name == name:
            return entry.fn(interface, *args)
    raise AssertionError(f"no method named {name}")


class MethodTests(unittest.TestCase):
    def test_load_profile_routes_to_daemon(self):
        daemon = FakeDaemon()
        interface = make_interface(daemon)
        self.assertTrue(call(interface, "LoadProfile", "wot"))
        self.assertEqual(daemon.loaded, ["wot"])

    def test_load_profile_reports_rejection(self):
        daemon = FakeDaemon(accept=False)
        interface = make_interface(daemon)
        self.assertFalse(call(interface, "LoadProfile", "nope"))

    def test_reload_routes_to_daemon(self):
        daemon = FakeDaemon()
        interface = make_interface(daemon)
        self.assertTrue(call(interface, "Reload"))
        self.assertEqual(daemon.reloads, 1)

    def test_list_profiles_returns_names(self):
        daemon = FakeDaemon(StateSnapshot(profile_names=("desktop", "wot")))
        interface = make_interface(daemon)
        self.assertEqual(call(interface, "ListProfiles"), ["desktop", "wot"])


class BindingMethodTests(unittest.TestCase):
    def test_set_binding_routes_to_the_daemon(self):
        daemon = FakeDaemon()
        interface = make_interface(daemon)
        self.assertTrue(call(interface, "SetBinding", "wot", 3, "key", "KEY_F"))
        binding = daemon.state.config.profile_named("wot").bindings[3]
        self.assertEqual((binding.type, binding.value), ("key", "KEY_F"))

    def test_set_binding_reports_rejection(self):
        daemon = FakeDaemon(accept=False)
        interface = make_interface(daemon)
        self.assertFalse(call(interface, "SetBinding", "wot", 3, "key", "KEY_F"))

    def test_clear_binding_routes_a_disabled_binding(self):
        """ADR-0003: never write NONE, so "clear" records a disabled binding."""
        daemon = FakeDaemon()
        interface = make_interface(daemon)
        self.assertTrue(call(interface, "ClearBinding", "wot", 3))
        binding = daemon.state.config.profile_named("wot").bindings.get(3)
        self.assertEqual(binding, Binding("disabled", None))


class LedMethodTests(unittest.TestCase):
    def test_set_leds_routes_to_the_daemon(self):
        daemon = FakeDaemon()
        interface = make_interface(daemon)
        ok = call(interface, "SetLeds", "wot", "breathing", 128, 3000, 10, 20, 30)
        self.assertTrue(ok)
        entry = daemon.state.config.profile_named("wot").leds[0]
        self.assertEqual(
            {key: entry[key] for key in ("mode", "brightness", "duration", "color")},
            {"mode": "breathing", "brightness": 128, "duration": 3000,
             "color": (10, 20, 30)},
        )

    def test_set_leds_reports_rejection(self):
        daemon = FakeDaemon(accept=False)
        ok = call(make_interface(daemon), "SetLeds", "wot", "on", 255, 0, 1, 2, 3)
        self.assertFalse(ok)


class GetViewTests(unittest.TestCase):
    """One read for everything a poll needs.

    Before GetView the client made nine sequential round trips per poll,
    with three separate failure policies. These tests pin the one struct
    that replaced them.
    """

    def test_view_returns_state_and_profile_sections(self):
        daemon = FakeDaemon(
            StateSnapshot(
                loaded_profile="wot", detected_game="x.exe",
                desktop_profile="desktop", profile_names=("desktop", "wot"),
            ),
            bindings={0: ("key", "KEY_F"), 3: ("special", "resolution-up")},
        )
        view = call(make_interface(daemon), "GetView", "wot")
        active, detected, desktop, names, bindings, leds, res, rates, rate = view
        self.assertEqual(active, "wot")
        self.assertEqual(detected, "x.exe")
        self.assertEqual(desktop, "desktop")
        self.assertEqual(list(names), ["desktop", "wot"])
        self.assertEqual(
            sorted(bindings),
            [(0, "key", "KEY_F"), (3, "special", "resolution-up")],
        )
        self.assertEqual(leds, [(0, "on", (0, 0, 0), 255, 0)])
        self.assertEqual(res, [(0, 800, 0, 0), (1, 1600, 0, 0)])
        self.assertEqual(list(rates), [125, 250, 500, 1000])
        self.assertEqual(rate, 0)

    def test_view_of_an_unknown_profile_has_empty_sections(self):
        """The UI may poll a profile that was just deleted."""
        view = call(make_interface(FakeDaemon()), "GetView", "nope")
        _active, _detected, _desktop, _names, bindings, leds, res, rates, rate = view
        self.assertEqual(bindings, [])
        self.assertEqual(leds, [])
        self.assertEqual(res, [])
        self.assertEqual(list(rates), [125, 250, 500, 1000])
        self.assertEqual(rate, 0)

    def test_view_report_rate_reports_the_profile(self):
        daemon = FakeDaemon()
        daemon.state.config = make_config(report_rate=500)
        view = call(make_interface(daemon), "GetView", "wot")
        self.assertEqual(view[-1], 500)

    def test_set_resolution_routes_to_the_daemon(self):
        daemon = FakeDaemon()
        interface = make_interface(daemon)
        self.assertTrue(call(interface, "SetResolution", "wot", 1, 1600, True, False))
        slot = daemon.state.config.profile_named("wot").resolutions[1]
        self.assertEqual((slot["dpi"], slot.get("default")), (1600, True))

    def test_set_resolution_reports_rejection(self):
        daemon = FakeDaemon(accept=False)
        self.assertFalse(
            call(make_interface(daemon), "SetResolution", "wot", 1, 1600, False, False)
        )

    def test_set_report_rate_routes_to_the_daemon(self):
        daemon = FakeDaemon()
        self.assertTrue(call(make_interface(daemon), "SetReportRate", "wot", 500))
        self.assertEqual(daemon.state.config.profile_named("wot").report_rate, 500)


class ProfileManagementMethodTests(unittest.TestCase):
    def test_create_routes_to_the_daemon(self):
        daemon = FakeDaemon()
        self.assertTrue(call(make_interface(daemon), "CreateProfile", "new", "New.exe"))
        self.assertIsNotNone(daemon.state.config.profile_named("new"))

    def test_create_reports_rejection(self):
        self.assertFalse(call(make_interface(FakeDaemon(accept=False)),
                              "CreateProfile", "new", ""))

    def test_rename_routes_to_the_daemon(self):
        daemon = FakeDaemon()
        self.assertTrue(call(make_interface(daemon), "RenameProfile", "wot", "wot2"))
        self.assertIsNotNone(daemon.state.config.profile_named("wot2"))

    def test_delete_routes_to_the_daemon(self):
        daemon = FakeDaemon()
        self.assertTrue(call(make_interface(daemon), "DeleteProfile", "wot"))
        self.assertIsNone(daemon.state.config.profile_named("wot"))

    def test_delete_reports_rejection(self):
        self.assertFalse(call(make_interface(FakeDaemon(accept=False)),
                              "DeleteProfile", "desktop"))


class PropertyTests(unittest.TestCase):
    def test_active_profile_reports_loaded(self):
        daemon = FakeDaemon(StateSnapshot(loaded_profile="world-of-tanks"))
        self.assertEqual(make_interface(daemon).ActiveProfile, "world-of-tanks")

    def test_active_profile_is_empty_when_unknown(self):
        daemon = FakeDaemon(StateSnapshot(loaded_profile=None))
        self.assertEqual(make_interface(daemon).ActiveProfile, "")

    def test_detected_game_is_empty_when_none(self):
        daemon = FakeDaemon(StateSnapshot(detected_game=None))
        self.assertEqual(make_interface(daemon).DetectedGame, "")

    def test_detected_game_reports_name(self):
        daemon = FakeDaemon(StateSnapshot(detected_game="world-of-tanks"))
        self.assertEqual(make_interface(daemon).DetectedGame, "world-of-tanks")

    def test_desktop_profile_reports_name(self):
        daemon = FakeDaemon(StateSnapshot(desktop_profile="desktop"))
        self.assertEqual(make_interface(daemon).DesktopProfile, "desktop")


class ReadmeTests(unittest.TestCase):
    """The README documents every member; this keeps it from drifting.

    The table listed three wrong signatures once, which is exactly the sort of
    thing that silently sends a reader down the wrong path.
    """

    def test_readme_documents_every_member(self):
        from pathlib import Path

        interface = make_interface(FakeDaemon())
        introspected = interface.introspect()
        names = (
            {m.name for m in introspected.methods}
            | {p.name for p in introspected.properties}
            | {s.name for s in introspected.signals}
        )
        readme = (Path(__file__).resolve().parent.parent / "README.md").read_text()
        missing = sorted(name for name in names if f"`{name}" not in readme)
        self.assertEqual(missing, [], f"undocumented D-Bus members: {missing}")

    def test_readme_signatures_match_introspection(self):
        import re
        from pathlib import Path

        interface = make_interface(FakeDaemon())
        readme = (Path(__file__).resolve().parent.parent / "README.md").read_text()
        for m in interface.introspect().methods:
            in_sig = "".join(a.signature for a in m.in_args)
            if not in_sig:
                continue
            # The table writes `Name(args) -> signature` for methods with inputs.
            pattern = rf"`{m.name}\([^`]*\)`\s*→\s*`([^`]+)`"
            match = re.search(pattern, readme)
            if match is None:
                continue
            self.assertEqual(
                match.group(1), in_sig,
                f"README signature for {m.name} is {match.group(1)}, actual {in_sig}",
            )


class BusAnnouncerTests(unittest.TestCase):
    """The daemon's events become the interface's signals."""

    class Interface:
        def __init__(self):
            self.emitted = []

        def ProfileChanged(self, name):
            self.emitted.append(("ProfileChanged", name))

        def GameDetected(self, name):
            self.emitted.append(("GameDetected", name))

        def GameExited(self, name):
            self.emitted.append(("GameExited", name))

        def ConfigChanged(self):
            self.emitted.append(("ConfigChanged",))

    def test_each_event_is_its_signal(self):
        from linghub.daemon.dbus_service import BusAnnouncer

        interface = self.Interface()
        announcer = BusAnnouncer()
        announcer.attach(interface)
        announcer.profile_loaded("wot")
        announcer.game_started("wot")
        announcer.game_stopped("wot")
        announcer.config_changed()
        self.assertEqual(interface.emitted, [
            ("ProfileChanged", "wot"),
            ("GameDetected", "wot"),
            ("GameExited", "wot"),
            ("ConfigChanged",),
        ])

    def test_nothing_is_announced_before_the_interface_is_published(self):
        from linghub.daemon.dbus_service import BusAnnouncer

        announcer = BusAnnouncer()
        announcer.config_changed()  # must not raise
        announcer.profile_loaded("wot")


class IntrospectionTests(unittest.TestCase):
    def test_interface_exposes_expected_members(self):
        interface = make_interface(FakeDaemon())
        introspected = interface.introspect()
        names = (
            {m.name for m in introspected.methods}
            | {p.name for p in introspected.properties}
            | {s.name for s in introspected.signals}
        )
        for member in (
            "LoadProfile", "Reload", "ListProfiles", "GetView",
            "SetBinding", "ClearBinding",
            "SetLeds",
            "SetResolution", "SetReportRate",
            "CreateProfile", "RenameProfile", "DeleteProfile",
            "ActiveProfile", "DetectedGame", "DesktopProfile",
            "ProfileChanged", "GameDetected", "GameExited", "ConfigChanged",
        ):
            self.assertIn(member, names, f"{member} missing from introspection")

    def test_interface_name_is_stable(self):
        self.assertEqual(INTERFACE, "org.linghub.Manager")


if __name__ == "__main__":
    unittest.main()
