"""Tests for the D-Bus manager interface.

The interface is a thin translation layer, so these tests check that it
routes calls to the daemon and reports state faithfully, without a bus.
"""

import unittest

from linghub.daemon.dbus_service import INTERFACE, ManagerInterface
from linghub.daemon.snapshot import StateSnapshot


class FakeDaemon:
    def __init__(self, snapshot=None, accept=True):
        self.snapshot = snapshot or StateSnapshot()
        self.accept = accept
        self.loaded: list[str] = []
        self.reloads = 0

    def on_load_profile(self, name):
        self.loaded.append(name)
        return self.accept

    def on_reload(self):
        self.reloads += 1
        return True

    def get_state(self):
        return self.snapshot


def make_interface(daemon):
    return ManagerInterface(
        on_load_profile=daemon.on_load_profile,
        on_reload=daemon.on_reload,
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
        self.assertTrue(call(interface, "LoadProfile", "world-of-tanks"))
        self.assertEqual(daemon.loaded, ["world-of-tanks"])

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
            "LoadProfile", "Reload", "ListProfiles",
            "ActiveProfile", "DetectedGame", "DesktopProfile",
            "ProfileChanged", "GameDetected", "GameExited",
        ):
            self.assertIn(member, names, f"{member} missing from introspection")

    def test_interface_name_is_stable(self):
        self.assertEqual(INTERFACE, "org.linghub.Manager")


if __name__ == "__main__":
    unittest.main()
