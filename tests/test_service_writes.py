"""Tests for the daemon's write paths.

Every write follows one rule: change the config, save it, and roll back in
memory if the save fails, so the running state never disagrees with the file.
These tests pin that rule for every path, so a new path cannot quietly skip it.
"""

import tempfile
import unittest
from pathlib import Path

from linghub.config import Config
from linghub.daemon.service import Daemon
from linghub.daemon.state import DaemonState
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


class WritePathTests(unittest.TestCase):
    """Each write path must save, and must roll back when saving fails."""

    def _daemon(self, save_ok=True):
        daemon = Daemon()
        daemon._state = DaemonState(config=make_config())
        daemon._saved = 0
        daemon._woken = 0

        def save():
            daemon._saved += 1
            return save_ok

        daemon._save_config = save
        daemon._wake = lambda: setattr(daemon, "_woken", daemon._woken + 1)
        return daemon

    # --- the paths -----------------------------------------------------

    def _writes(self):
        return {
            "binding": lambda d: d._request_set_binding("wot", 1, "key", "KEY_B"),
            "leds": lambda d: d._request_set_leds(
                "wot", {"mode": "breathing", "brightness": 100,
                        "duration": 1000, "color": (1, 2, 3)}
            ),
            "resolution": lambda d: d._request_set_resolution("wot", 0, 1200, False, False),
            "report_rate": lambda d: d._request_set_report_rate("wot", 500),
            "create": lambda d: d._request_create_profile("new", ""),
            "rename": lambda d: d._request_rename_profile("wot", "wot2"),
            "delete": lambda d: d._request_delete_profile("wot"),
        }

    def test_every_path_saves_the_config(self):
        for name, write in self._writes().items():
            with self.subTest(path=name):
                daemon = self._daemon()
                self.assertTrue(write(daemon), f"{name} was rejected")
                self.assertEqual(daemon._saved, 1, f"{name} did not save")

    def test_every_path_wakes_the_loop(self):
        """A change that does not wake the daemon is never pushed to the mouse."""
        for name, write in self._writes().items():
            with self.subTest(path=name):
                daemon = self._daemon()
                write(daemon)
                self.assertEqual(daemon._woken, 1, f"{name} did not wake the loop")

    def test_every_path_rolls_back_when_saving_fails(self):
        for name, write in self._writes().items():
            with self.subTest(path=name):
                daemon = self._daemon(save_ok=False)
                before = daemon._state.config
                self.assertFalse(write(daemon), f"{name} reported success")
                self.assertIs(
                    daemon._state.config, before,
                    f"{name} left the config changed after a failed save",
                )

    def test_a_failed_save_does_not_wake_the_loop(self):
        for name, write in self._writes().items():
            with self.subTest(path=name):
                daemon = self._daemon(save_ok=False)
                write(daemon)
                self.assertEqual(daemon._woken, 0, f"{name} woke the loop anyway")


class ValidationTests(unittest.TestCase):
    """Validation must happen before the config is touched."""

    def _daemon(self):
        daemon = Daemon()
        daemon._state = DaemonState(config=make_config())
        daemon._saved = 0
        daemon._save_config = lambda: True
        daemon._wake = lambda: None
        return daemon

    def test_an_unknown_binding_type_is_rejected(self):
        daemon = self._daemon()
        self.assertFalse(daemon._request_set_binding("wot", 1, "nonsense", "x"))
        self.assertEqual(daemon._saved, 0)

    def test_an_invalid_led_setting_is_rejected(self):
        daemon = self._daemon()
        self.assertFalse(daemon._request_set_leds("wot", {"mode": "strobe"}))
        self.assertEqual(daemon._saved, 0)

    def test_an_out_of_range_brightness_is_rejected(self):
        daemon = self._daemon()
        self.assertFalse(
            daemon._request_set_leds("wot", {"mode": "on", "brightness": 999})
        )
        self.assertEqual(daemon._saved, 0)

    def test_an_unknown_profile_is_rejected(self):
        daemon = self._daemon()
        self.assertFalse(daemon._request_set_binding("nope", 1, "key", "KEY_B"))
        self.assertEqual(daemon._saved, 0)


if __name__ == "__main__":
    unittest.main()
