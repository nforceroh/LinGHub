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


if __name__ == "__main__":
    unittest.main()
