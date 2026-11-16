"""Tests for config loading."""

import json
import tempfile
import unittest
from pathlib import Path

from linghub import config as config_module
from linghub.config import ConfigError, load


def write_config(directory: Path, body: dict) -> Path:
    path = directory / "config.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


MINIMAL = {
    "version": 1,
    "settings": {"desktop_profile": "desktop"},
    "profiles": {"desktop": {"games": []}},
}


class LoadTests(unittest.TestCase):
    def test_loads_minimal_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = load(write_config(Path(tmp), MINIMAL))
        self.assertEqual(config.desktop_profile, "desktop")
        self.assertEqual(len(config.profiles), 1)
        self.assertEqual(config.poll_interval, 2.0)

    def test_desktop_profile_is_resolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = load(write_config(Path(tmp), MINIMAL))
        self.assertIsNotNone(config.desktop)
        self.assertTrue(config.desktop.is_desktop)

    def test_parses_games_and_bindings(self):
        body = {
            "version": 1,
            "settings": {"desktop_profile": "desktop"},
            "profiles": {
                "desktop": {"games": []},
                "wot": {
                    "games": ["WorldOfTanks.exe"],
                    "bindings": {"3": {"type": "key", "value": "KEY_F"}},
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            config = load(write_config(Path(tmp), body))
        wot = config.profile_named("wot")
        self.assertEqual(wot.games[0].executable, "WorldOfTanks.exe")
        self.assertEqual(wot.bindings[3].type, "key")
        self.assertEqual(wot.bindings[3].value, "KEY_F")

    def test_missing_file_raises(self):
        with self.assertRaisesRegex(ConfigError, "config not found"):
            load("/nonexistent/config.json")

    def test_invalid_json_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "not valid JSON"):
                load(path)

    def test_unsupported_version_raises(self):
        body = dict(MINIMAL, version=99)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ConfigError, "unsupported config version"):
                load(write_config(Path(tmp), body))

    def test_missing_desktop_profile_raises(self):
        body = {
            "version": 1,
            "settings": {"desktop_profile": "nope"},
            "profiles": {"desktop": {"games": []}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ConfigError, "desktop profile 'nope' is not defined"):
                load(write_config(Path(tmp), body))

    def test_empty_profiles_raises(self):
        body = {"version": 1, "settings": {}, "profiles": {}}
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ConfigError, "at least one profile"):
                load(write_config(Path(tmp), body))

    def test_invalid_binding_type_raises(self):
        body = {
            "version": 1,
            "settings": {"desktop_profile": "desktop"},
            "profiles": {"desktop": {"games": [], "bindings": {"0": {"type": "nonsense"}}}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                load(write_config(Path(tmp), body))

    def test_example_config_is_valid(self):
        example = Path(__file__).resolve().parent.parent / "config.example.json"
        config = load(example)
        self.assertIsNotNone(config.desktop)
        self.assertIsNotNone(config.profile_named("world-of-tanks"))


class SaveTests(unittest.TestCase):
    """Round-trip: what is written must load back identically.

    The daemon is the only writer (ADR-0004), so saving has to preserve the
    parts of the file it does not understand rather than dropping them.
    """

    def _roundtrip(self, body):
        from linghub.config import save

        with tempfile.TemporaryDirectory() as tmp:
            path = write_config(Path(tmp), body)
            config = load(path)
            from linghub.domain.profile import Binding

            profile = config.profile_named("wot")
            if profile is not None:
                profile.bindings[3] = Binding(type="special", value="resolution-up")
            save(path, config)
            return load(path)

    def test_binding_survives_a_save(self):
        body = {
            "version": 1,
            "settings": {"desktop_profile": "desktop"},
            "profiles": {
                "desktop": {"games": []},
                "wot": {"games": ["WorldOfTanks.exe"],
                        "bindings": {"3": {"type": "key", "value": "KEY_F"}}},
            },
        }
        reloaded = self._roundtrip(body)
        wot = reloaded.profile_named("wot")
        self.assertEqual(wot.bindings[3].type, "special")
        self.assertEqual(wot.bindings[3].value, "resolution-up")

    def test_untouched_parts_are_preserved(self):
        """Keys the daemon does not model must not be dropped."""
        body = {
            "version": 1,
            "settings": {"desktop_profile": "desktop", "poll_interval": 3},
            "profiles": {
                "desktop": {"games": []},
                "wot": {"games": ["WorldOfTanks.exe"],
                        "report_rate": 500,
                        "bindings": {"3": {"type": "key", "value": "KEY_F"}}},
            },
            "x-custom": {"keep": "me"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = write_config(Path(tmp), body)
            config = load(path)
            from linghub.config import save
            save(path, config)
            raw = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(raw["x-custom"], {"keep": "me"})
        self.assertEqual(raw["profiles"]["wot"]["report_rate"], 500)
        self.assertEqual(raw["settings"]["poll_interval"], 3)

    def test_save_is_validated_before_replacing(self):
        """A bad config must not clobber the file on disk."""
        body = {
            "version": 1,
            "settings": {"desktop_profile": "desktop"},
            "profiles": {"desktop": {"games": []}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = write_config(Path(tmp), body)
            original = path.read_text(encoding="utf-8")
            config = load(path)
            config.profiles.clear()  # now invalid: no profiles at all
            from linghub.config import save
            from linghub.config import ConfigError
            with self.assertRaises(ConfigError):
                save(path, config)
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_save_preserves_desktop_settings(self):
        body = {
            "version": 1,
            "settings": {"desktop_profile": "desktop"},
            "profiles": {"desktop": {"games": []}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = write_config(Path(tmp), body)
            from linghub.config import save
            save(path, load(path))
            reloaded = load(path)
        self.assertEqual(reloaded.desktop_profile, "desktop")


class LedValidationTests(unittest.TestCase):
    """LED settings are written straight to hardware, so validate on load.

    An out-of-range brightness or an unknown mode would otherwise fail deep
    inside the writer, or silently do nothing.
    """

    BASE = {
        "version": 1,
        "settings": {"desktop_profile": "desktop"},
        "profiles": {"desktop": {"games": []}},
    }

    def _load_with_leds(self, leds):
        body = json.loads(json.dumps(self.BASE))
        body["profiles"]["desktop"]["leds"] = leds
        with tempfile.TemporaryDirectory() as tmp:
            return load(write_config(Path(tmp), body))

    def test_valid_leds_load(self):
        config = self._load_with_leds([
            {"index": 0, "mode": "on", "color": [255, 0, 0], "brightness": 128},
        ])
        self.assertEqual(config.desktop.leds[0]["mode"], "on")

    def test_unknown_mode_raises(self):
        with self.assertRaisesRegex(ConfigError, "mode"):
            self._load_with_leds([{"index": 0, "mode": "strobe"}])

    def test_brightness_above_255_raises(self):
        with self.assertRaisesRegex(ConfigError, "brightness"):
            self._load_with_leds([{"index": 0, "mode": "on", "brightness": 256}])

    def test_negative_brightness_raises(self):
        with self.assertRaisesRegex(ConfigError, "brightness"):
            self._load_with_leds([{"index": 0, "mode": "on", "brightness": -1}])

    def test_color_must_be_three_channels(self):
        with self.assertRaisesRegex(ConfigError, "color"):
            self._load_with_leds([{"index": 0, "mode": "on", "color": [255, 0]}])

    def test_color_channels_must_be_in_range(self):
        with self.assertRaisesRegex(ConfigError, "color"):
            self._load_with_leds([{"index": 0, "mode": "on", "color": [300, 0, 0]}])

    def test_led_needs_an_index(self):
        with self.assertRaisesRegex(ConfigError, "index"):
            self._load_with_leds([{"mode": "on"}])

    def test_leds_round_trip_through_save(self):
        from linghub.config import save

        body = json.loads(json.dumps(self.BASE))
        body["profiles"]["desktop"]["leds"] = [
            {"index": 0, "mode": "on", "color": [1, 2, 3], "brightness": 200},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = write_config(Path(tmp), body)
            config = load(path)
            save(path, config)
            again = load(path)
            raw = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(again.desktop.leds, config.desktop.leds)
        self.assertEqual(raw["profiles"]["desktop"]["leds"][0]["color"], [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
