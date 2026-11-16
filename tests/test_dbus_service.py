"""Tests for the D-Bus manager interface.

The interface is a thin translation layer, so these tests check that it
routes calls to the daemon and reports state faithfully, without a bus.
"""

import unittest

from linghub.daemon.dbus_service import INTERFACE, ManagerInterface
from linghub.daemon.snapshot import StateSnapshot


class FakeDaemon:
    def __init__(self, snapshot=None, accept=True, bindings=None):
        self.snapshot = snapshot or StateSnapshot()
        self.accept = accept
        self.loaded: list[str] = []
        self.reloads = 0
        self.bindings = bindings or {}
        self.set_calls: list[tuple] = []

    def on_load_profile(self, name):
        self.loaded.append(name)
        return self.accept

    def on_reload(self):
        self.reloads += 1
        return True

    def get_state(self):
        return self.snapshot

    def get_bindings(self, profile):
        return self.bindings

    def on_set_binding(self, profile, index, kind, value):
        self.set_calls.append((profile, index, kind, value))
        return self.accept

    def get_leds(self, profile):
        return getattr(self, "leds", {})

    def on_set_leds(self, profile, settings):
        self.led_calls = getattr(self, "led_calls", [])
        self.led_calls.append((profile, settings))
        return self.accept


def make_interface(daemon):
    return ManagerInterface(
        on_load_profile=daemon.on_load_profile,
        on_reload=daemon.on_reload,
        get_state=daemon.get_state,
        get_bindings=daemon.get_bindings,
        on_set_binding=daemon.on_set_binding,
        get_leds=daemon.get_leds,
        on_set_leds=daemon.on_set_leds,
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


class BindingMethodTests(unittest.TestCase):
    def test_get_bindings_returns_pairs(self):
        daemon = FakeDaemon(bindings={0: ("key", "KEY_F"), 3: ("special", "resolution-up")})
        interface = make_interface(daemon)
        self.assertEqual(
            sorted(call(interface, "GetBindings", "wot")),
            [(0, "key", "KEY_F"), (3, "special", "resolution-up")],
        )

    def test_get_bindings_returns_empty_for_an_unknown_profile(self):
        daemon = FakeDaemon(bindings={})
        self.assertEqual(call(make_interface(daemon), "GetBindings", "nope"), [])

    def test_set_binding_routes_to_the_daemon(self):
        daemon = FakeDaemon()
        interface = make_interface(daemon)
        self.assertTrue(call(interface, "SetBinding", "wot", 3, "key", "KEY_F"))
        self.assertEqual(daemon.set_calls, [("wot", 3, "key", "KEY_F")])

    def test_set_binding_reports_rejection(self):
        daemon = FakeDaemon(accept=False)
        interface = make_interface(daemon)
        self.assertFalse(call(interface, "SetBinding", "wot", 3, "key", "KEY_F"))

    def test_clear_binding_routes_a_disabled_binding(self):
        """ADR-0003: never write NONE, so "clear" means a harmless special."""
        daemon = FakeDaemon()
        interface = make_interface(daemon)
        self.assertTrue(call(interface, "ClearBinding", "wot", 3))
        self.assertEqual(daemon.set_calls, [("wot", 3, "disabled", None)])


class LedMethodTests(unittest.TestCase):
    def test_get_leds_returns_settings(self):
        daemon = FakeDaemon()
        daemon.leds = {0: {"mode": "on", "color": (255, 0, 0), "brightness": 128}}
        interface = make_interface(daemon)
        self.assertEqual(
            call(interface, "GetLeds", "wot"),
            [(0, "on", (255, 0, 0), 128, 0)],
        )

    def test_get_leds_empty_for_unknown_profile(self):
        self.assertEqual(call(make_interface(FakeDaemon()), "GetLeds", "nope"), [])

    def test_set_leds_routes_to_the_daemon(self):
        daemon = FakeDaemon()
        interface = make_interface(daemon)
        ok = call(interface, "SetLeds", "wot", "breathing", 128, 3000, 10, 20, 30)
        self.assertTrue(ok)
        self.assertEqual(
            daemon.led_calls,
            [("wot", {"mode": "breathing", "brightness": 128, "duration": 3000,
                      "color": (10, 20, 30)})],
        )

    def test_set_leds_reports_rejection(self):
        daemon = FakeDaemon(accept=False)
        ok = call(make_interface(daemon), "SetLeds", "wot", "on", 255, 0, 1, 2, 3)
        self.assertFalse(ok)


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
            "GetBindings", "SetBinding", "ClearBinding",
            "GetLeds", "SetLeds",
            "ActiveProfile", "DetectedGame", "DesktopProfile",
            "ProfileChanged", "GameDetected", "GameExited",
        ):
            self.assertIn(member, names, f"{member} missing from introspection")

    def test_interface_name_is_stable(self):
        self.assertEqual(INTERFACE, "org.linghub.Manager")


if __name__ == "__main__":
    unittest.main()
