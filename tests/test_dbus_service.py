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

    def get_resolutions(self, profile):
        return getattr(self, "resolutions", ())

    def get_report_rate(self, profile):
        return getattr(self, "report_rate", 0)

    def get_report_rates(self, profile):
        return getattr(self, "report_rates", (125, 250, 500, 1000))

    def on_set_resolution(self, profile, index, dpi, make_default, disabled):
        self.res_calls = getattr(self, "res_calls", [])
        self.res_calls.append((profile, index, dpi, make_default, disabled))
        return self.accept

    def on_create_profile(self, name, executable):
        self.created = getattr(self, "created", [])
        self.created.append((name, executable))
        return self.accept

    def on_rename_profile(self, old, new):
        self.renamed = getattr(self, "renamed", [])
        self.renamed.append((old, new))
        return self.accept

    def on_delete_profile(self, name):
        self.deleted = getattr(self, "deleted", [])
        self.deleted.append(name)
        return self.accept

    def on_set_report_rate(self, profile, rate):
        self.rate_calls = getattr(self, "rate_calls", [])
        self.rate_calls.append((profile, rate))
        return self.accept


class FakeProfiles:
    """The profile-lifecycle collaborator, backed by FakeDaemon."""

    def __init__(self, daemon):
        self._daemon = daemon

    def load(self, name):
        return self._daemon.on_load_profile(name)

    def reload(self):
        return self._daemon.on_reload()

    def create(self, name, executable):
        return self._daemon.on_create_profile(name, executable)

    def rename(self, old, new):
        return self._daemon.on_rename_profile(old, new)

    def delete(self, name):
        return self._daemon.on_delete_profile(name)


class FakeBindings:
    def __init__(self, daemon):
        self._daemon = daemon

    def get(self, profile):
        return self._daemon.get_bindings(profile)

    def set(self, profile, index, kind, value):
        return self._daemon.on_set_binding(profile, index, kind, value)

    def clear(self, profile, index):
        return self._daemon.on_set_binding(profile, index, "disabled", None)


class FakeSettings:
    def __init__(self, daemon):
        self._daemon = daemon

    def get_resolutions(self, profile):
        return self._daemon.get_resolutions(profile)

    def set_resolution(self, profile, index, dpi, make_default, disabled):
        return self._daemon.on_set_resolution(profile, index, dpi, make_default, disabled)

    def get_report_rate(self, profile):
        return self._daemon.get_report_rate(profile)

    def get_report_rates(self, profile):
        return self._daemon.get_report_rates(profile)

    def set_report_rate(self, profile, rate):
        return self._daemon.on_set_report_rate(profile, rate)

    def get_leds(self, profile):
        return self._daemon.get_leds(profile)

    def set_leds(self, profile, settings):
        return self._daemon.on_set_leds(profile, settings)


def make_interface(daemon):
    return ManagerInterface(
        profiles=FakeProfiles(daemon),
        bindings=FakeBindings(daemon),
        settings=FakeSettings(daemon),
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


class DpiMethodTests(unittest.TestCase):
    def test_get_resolutions_returns_slots(self):
        daemon = FakeDaemon()
        daemon.resolutions = (
            (400, False, False),
            (800, True, False),
            (100, False, True),
        )
        interface = make_interface(daemon)
        self.assertEqual(
            call(interface, "GetResolutions", "wot"),
            [(0, 400, 0, 0), (1, 800, 1, 0), (2, 100, 0, 1)],
        )

    def test_get_resolutions_empty_for_unknown_profile(self):
        self.assertEqual(call(make_interface(FakeDaemon()), "GetResolutions", "nope"), [])

    def test_report_rate_is_exposed(self):
        daemon = FakeDaemon()
        daemon.report_rate = 500
        self.assertEqual(call(make_interface(daemon), "GetReportRate", "wot"), 500)

    def test_report_rates_are_exposed(self):
        daemon = FakeDaemon()
        daemon.report_rates = (125, 250)
        self.assertEqual(call(make_interface(daemon), "GetReportRates", "wot"), [125, 250])

    def test_set_resolution_routes_to_the_daemon(self):
        daemon = FakeDaemon()
        ok = call(make_interface(daemon), "SetResolution", "wot", 1, 1600, True, False)
        self.assertTrue(ok)
        self.assertEqual(daemon.res_calls, [("wot", 1, 1600, True, False)])

    def test_set_resolution_reports_rejection(self):
        daemon = FakeDaemon(accept=False)
        self.assertFalse(call(make_interface(daemon), "SetResolution", "wot", 1, 1600, False, False))

    def test_set_report_rate_routes_to_the_daemon(self):
        daemon = FakeDaemon()
        self.assertTrue(call(make_interface(daemon), "SetReportRate", "wot", 500))
        self.assertEqual(daemon.rate_calls, [("wot", 500)])


class ProfileManagementMethodTests(unittest.TestCase):
    def test_create_routes_to_the_daemon(self):
        daemon = FakeDaemon()
        self.assertTrue(call(make_interface(daemon), "CreateProfile", "new", "New.exe"))
        self.assertEqual(daemon.created, [("new", "New.exe")])

    def test_create_reports_rejection(self):
        self.assertFalse(call(make_interface(FakeDaemon(accept=False)),
                              "CreateProfile", "new", ""))

    def test_rename_routes_to_the_daemon(self):
        daemon = FakeDaemon()
        self.assertTrue(call(make_interface(daemon), "RenameProfile", "old", "new"))
        self.assertEqual(daemon.renamed, [("old", "new")])

    def test_delete_routes_to_the_daemon(self):
        daemon = FakeDaemon()
        self.assertTrue(call(make_interface(daemon), "DeleteProfile", "old"))
        self.assertEqual(daemon.deleted, ["old"])

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
            "GetResolutions", "SetResolution", "GetReportRate", "SetReportRate",
            "GetReportRates", "CreateProfile", "RenameProfile", "DeleteProfile",
            "ActiveProfile", "DetectedGame", "DesktopProfile",
            "ProfileChanged", "GameDetected", "GameExited",
        ):
            self.assertIn(member, names, f"{member} missing from introspection")

    def test_interface_name_is_stable(self):
        self.assertEqual(INTERFACE, "org.linghub.Manager")


if __name__ == "__main__":
    unittest.main()
