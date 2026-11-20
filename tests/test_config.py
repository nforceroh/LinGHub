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
            # ConfigError, not a bare ValueError: the daemon catches ConfigError
            # when it reloads, so anything else would escape and kill it.
            with self.assertRaisesRegex(ConfigError, "unknown binding type"):
                load(write_config(Path(tmp), body))

    def test_a_non_numeric_button_value_raises(self):
        body = {
            "version": 1,
            "settings": {"desktop_profile": "desktop"},
            "profiles": {"desktop": {"games": [], "bindings": {"0": {"type": "button",
                                                                   "value": "left"}}}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ConfigError, "must be a number"):
                load(write_config(Path(tmp), body))

    def test_a_button_value_written_as_text_is_normalised(self):
        """Older configs hold "9" where a hand-written file holds 9.

        Both encode to the same hardware action, so nothing ever failed - but
        the two files disagreed, and the next save is what heals it.
        """
        body = {
            "version": 1,
            "settings": {"desktop_profile": "desktop"},
            "profiles": {"desktop": {"games": [], "bindings": {"0": {"type": "button",
                                                                   "value": "9"}}}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            loaded = load(write_config(Path(tmp), body))
            self.assertEqual(loaded.desktop.bindings[0].value, 9)
            self.assertIsInstance(loaded.desktop.bindings[0].value, int)

    def test_example_config_is_valid(self):
        example = Path(__file__).resolve().parent.parent / "config.example.json"
        config = load(example)
        self.assertIsNotNone(config.desktop)
        self.assertIsNotNone(config.profile_named("world-of-tanks"))


class UnencodableBindingTests(unittest.TestCase):
    """A binding the hardware can't encode is refused on the way in (#8).

    It used to load fine and crash the daemon on its first write, and since
    the config still loaded, systemd restarted it into the same crash.
    """

    def _body(self, binding):
        return {
            "version": 1,
            "settings": {"desktop_profile": "desktop"},
            "profiles": {"desktop": {"games": [], "bindings": {"3": binding}}},
        }

    def test_an_unknown_key_name_is_rejected_naming_the_button(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ConfigError, r"binding '3' is invalid: .*KEY_BOGUS"):
                load(write_config(Path(tmp), self._body({"type": "key", "value": "KEY_BOGUS"})))

    def test_an_unknown_key_inside_a_macro_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ConfigError, "KEY_NOPE"):
                load(write_config(Path(tmp), self._body({"type": "macro", "value": "KEY_A KEY_NOPE"})))

    def test_an_encodable_binding_still_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = load(write_config(Path(tmp), self._body({"type": "key", "value": "KEY_F"})))
        self.assertEqual(config.desktop.bindings[3].value, "KEY_F")


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


class FactoryDefaultTests(unittest.TestCase):
    """The config a fresh install starts with, and `linghub init` writing it."""

    def test_factory_default_has_one_desktop_profile(self):
        config = config_module.factory_default()
        self.assertEqual([p.name for p in config.profiles], ["desktop"])
        self.assertEqual(config.desktop_profile, "desktop")
        self.assertTrue(config.desktop.is_desktop)

    def test_factory_default_round_trips_through_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "config.json"
            config_module.write_default(path)
            loaded = load(path)
        self.assertEqual(loaded.desktop_profile, "desktop")
        self.assertEqual(loaded.desktop.report_rate, 1000)
        self.assertEqual(len(loaded.desktop.resolutions), 3)
        self.assertEqual(loaded.desktop.bindings[7].value, "resolution-up")
        self.assertEqual(len(loaded.desktop.leds), 2)

    def test_write_default_creates_the_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a" / "b" / "config.json"
            config_module.write_default(path)
            self.assertTrue(path.exists())

    def test_write_default_refuses_to_replace_an_existing_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text('{"version": 1, "profiles": {"mine": {}}}', encoding="utf-8")
            with self.assertRaises(ConfigError):
                config_module.write_default(path)
            self.assertIn("mine", path.read_text(encoding="utf-8"))

    def test_write_default_leaves_a_broken_config_alone(self):
        """A broken config must fail loudly at daemon start, not be replaced."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text("not json", encoding="utf-8")
            with self.assertRaises(ConfigError):
                config_module.write_default(path)
            self.assertEqual(path.read_text(encoding="utf-8"), "not json")
