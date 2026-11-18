"""Tests for the daemon's write paths.

Every write follows one rule: change the config, save it, and roll back in
memory if the save fails, so the running state never disagrees with the file.
These tests pin that rule for every path, so a new path cannot quietly skip it.

The rule lives in `ConfigWrites.apply`, and the paths are the collaborators in
`writes.py`. Testing them there rather than through the daemon is the point of
extracting them: the rule can be exercised without a bus, a device, or a
running loop.
"""

import unittest

from linghub.config import Config
from linghub.daemon.state import DaemonState
from linghub.daemon.writes import (
    Bindings,
    ConfigWrites,
    DeviceSettings,
    ProfileLifecycle,
)
from linghub.domain.profile import Binding, Game, Profile


def make_config() -> Config:
    return Config(
        profiles=[
            Profile(name="desktop"),
            Profile(name="wot", games=(Game("x.exe"),),
                    bindings={0: Binding("key", "KEY_A")},
                    resolutions=({"dpi": 800}, {"dpi": 1600}),
                    leds=({"index": 0, "mode": "on"},)),
        ],
        desktop_profile="desktop",
        poll_interval=2.0,
    )


class _Harness:
    """The collaborators wired to a state, counting saves and wakes."""

    def __init__(self, save_ok: bool = True):
        self.state: DaemonState | None = DaemonState(config=make_config())
        self.saved = 0
        self.woken = 0
        self.announced = 0
        self.loaded: list[str] = []
        self.reloads = 0
        self._save_ok = save_ok

        writes = ConfigWrites(
            state=lambda: self.state,
            save=self._save,
            wake=self._wake,
            announce=self._announce,
        )
        self.profiles = ProfileLifecycle(
            state=lambda: self.state,
            writes=writes,
            request_load=self._load,
            request_reload=self._reload,
        )
        self.bindings = Bindings(state=lambda: self.state, writes=writes)
        self.settings = DeviceSettings(
            state=lambda: self.state,
            writes=writes,
            report_rates=lambda: (125, 250, 500, 1000),
        )

    def _save(self) -> bool:
        self.saved += 1
        return self._save_ok

    def _wake(self) -> None:
        self.woken += 1

    def _announce(self) -> None:
        self.announced += 1

    def _load(self, name: str) -> bool:
        self.loaded.append(name)
        return True

    def _reload(self) -> bool:
        self.reloads += 1
        return True


def _paths(h: _Harness) -> dict:
    """Every write path, so a new one cannot skip the rule."""
    return {
        "binding": lambda: h.bindings.set("wot", 1, "key", "KEY_B"),
        "clear": lambda: h.bindings.clear("wot", 1),
        "leds": lambda: h.settings.set_leds(
            "wot", {"mode": "breathing", "brightness": 100,
                    "duration": 1000, "color": (1, 2, 3)}
        ),
        "resolution": lambda: h.settings.set_resolution("wot", 0, 1200, False, False),
        "report_rate": lambda: h.settings.set_report_rate("wot", 500),
        "create": lambda: h.profiles.create("new", ""),
        "rename": lambda: h.profiles.rename("wot", "wot2"),
        "delete": lambda: h.profiles.delete("wot"),
    }


class WritePathTests(unittest.TestCase):
    """Each write path must save, and must roll back when saving fails."""

    def test_every_path_saves_the_config(self):
        for name, write in _paths(_Harness()).items():
            with self.subTest(path=name):
                h = _Harness()
                self.assertTrue(_paths(h)[name](), f"{name} was rejected")
                self.assertEqual(h.saved, 1, f"{name} did not save")

    def test_every_path_wakes_the_loop(self):
        """A change that does not wake the daemon is never pushed to the mouse."""
        for name, write in _paths(_Harness()).items():
            with self.subTest(path=name):
                h = _Harness()
                _paths(h)[name]()
                self.assertEqual(h.woken, 1, f"{name} did not wake the loop")

    def test_every_path_announces_the_change(self):
        """The tray's profile menu and the window rely on hearing about it."""
        for name, write in _paths(_Harness()).items():
            with self.subTest(path=name):
                h = _Harness()
                _paths(h)[name]()
                self.assertEqual(h.announced, 1, f"{name} was not announced")

    def test_every_path_rolls_back_when_saving_fails(self):
        for name, write in _paths(_Harness()).items():
            with self.subTest(path=name):
                h = _Harness(save_ok=False)
                before = h.state.config
                self.assertFalse(_paths(h)[name](), f"{name} reported success")
                self.assertIs(
                    h.state.config, before,
                    f"{name} left the config changed after a failed save",
                )

    def test_a_failed_save_does_not_wake_the_loop(self):
        for name, write in _paths(_Harness()).items():
            with self.subTest(path=name):
                h = _Harness(save_ok=False)
                _paths(h)[name]()
                self.assertEqual(h.woken, 0, f"{name} woke the loop anyway")

    def test_a_failed_save_announces_nothing(self):
        for name, write in _paths(_Harness()).items():
            with self.subTest(path=name):
                h = _Harness(save_ok=False)
                _paths(h)[name]()
                self.assertEqual(h.announced, 0, f"{name} announced a change it undid")

    def test_a_write_with_no_config_yet_is_refused(self):
        """Startup reads the config first, but a race must not crash."""
        h = _Harness()
        h.state = None
        self.assertFalse(h.bindings.set("wot", 1, "key", "KEY_B"))
        self.assertEqual(h.saved, 0)


class ValidationTests(unittest.TestCase):
    """Validation must happen before the config is touched."""

    def test_an_unknown_binding_type_is_rejected(self):
        h = _Harness()
        self.assertFalse(h.bindings.set("wot", 1, "nonsense", "x"))
        self.assertEqual(h.saved, 0)

    def test_an_invalid_led_setting_is_rejected(self):
        h = _Harness()
        self.assertFalse(h.settings.set_leds("wot", {"mode": "strobe"}))
        self.assertEqual(h.saved, 0)

    def test_an_out_of_range_brightness_is_rejected(self):
        h = _Harness()
        self.assertFalse(h.settings.set_leds("wot", {"mode": "on", "brightness": 999}))
        self.assertEqual(h.saved, 0)

    def test_an_unknown_profile_is_rejected(self):
        h = _Harness()
        self.assertFalse(h.bindings.set("nope", 1, "key", "KEY_B"))
        self.assertEqual(h.saved, 0)


class ReadPathTests(unittest.TestCase):
    """The read paths answer for a known profile and shrug at an unknown one."""

    def test_bindings_are_returned_by_ratbag_index(self):
        self.assertEqual(_Harness().bindings.get("wot"), {0: ("key", "KEY_A")})

    def test_bindings_are_empty_for_an_unknown_profile(self):
        self.assertEqual(_Harness().bindings.get("nope"), {})

    def test_resolutions_are_returned_in_order(self):
        self.assertEqual(
            _Harness().settings.get_resolutions("wot"),
            ((800, False, False), (1600, False, False)),
        )

    def test_resolutions_are_empty_for_an_unknown_profile(self):
        self.assertEqual(_Harness().settings.get_resolutions("nope"), ())

    def test_report_rate_is_zero_when_unset(self):
        self.assertEqual(_Harness().settings.get_report_rate("wot"), 0)

    def test_report_rates_come_from_the_device(self):
        self.assertEqual(
            _Harness().settings.get_report_rates("wot"), (125, 250, 500, 1000)
        )

    def test_leds_are_keyed_by_index(self):
        self.assertEqual(
            _Harness().settings.get_leds("wot"), {0: {"index": 0, "mode": "on"}}
        )

    def test_leds_are_empty_for_an_unknown_profile(self):
        self.assertEqual(_Harness().settings.get_leds("nope"), {})


class LoadTests(unittest.TestCase):
    """Loading is not a config write: it changes what is on the mouse."""

    def test_load_asks_the_daemon_to_load(self):
        h = _Harness()
        self.assertTrue(h.profiles.load("wot"))
        self.assertEqual(h.loaded, ["wot"])
        self.assertEqual(h.saved, 0, "loading must not rewrite the config")

    def test_load_of_an_unknown_profile_is_refused(self):
        """A queued bad name would only fail again on the next tick."""
        h = _Harness()
        self.assertFalse(h.profiles.load("nope"))
        self.assertEqual(h.loaded, [])

    def test_reload_asks_the_daemon_to_reread(self):
        h = _Harness()
        self.assertTrue(h.profiles.reload())
        self.assertEqual(h.reloads, 1)


if __name__ == "__main__":
    unittest.main()