"""Tests for the battery read.

The reader walks sysfs, so these build a fake power-supply directory rather than
depending on what is plugged into the machine running the tests.
"""

import tempfile
import unittest
from pathlib import Path

from linghub.hardware.battery import Battery, battery, model_name


def _supply(tmp: str, name: str, **values) -> Path:
    entry = Path(tmp) / name
    entry.mkdir(parents=True)
    for key, value in values.items():
        entry.joinpath(key).write_text(f"{value}\n", encoding="utf-8")
    return entry


class BatteryTests(unittest.TestCase):
    def test_reads_capacity_and_charging(self):
        with tempfile.TemporaryDirectory() as tmp:
            _supply(tmp, "hidpp_battery_0", capacity=85, status="Discharging")
            result = battery(Path(tmp))
        self.assertEqual(result, Battery(capacity=85, charging=False))

    def test_a_charging_mouse_is_reported_as_charging(self):
        with tempfile.TemporaryDirectory() as tmp:
            _supply(tmp, "hidpp_battery_0", capacity=40, status="Charging")
            result = battery(Path(tmp))
        self.assertTrue(result.charging)

    def test_the_status_is_matched_case_insensitively(self):
        with tempfile.TemporaryDirectory() as tmp:
            _supply(tmp, "hidpp_battery_0", capacity=40, status="CHARGING")
            result = battery(Path(tmp))
        self.assertTrue(result.charging)

    def test_a_wired_mouse_has_no_battery(self):
        """No hidpp device is not an error; it is a mouse with no battery."""
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(battery(Path(tmp)))

    def test_a_missing_sysfs_is_not_an_error(self):
        self.assertIsNone(battery(Path("/nonexistent/power_supply")))

    def test_an_unreadable_capacity_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            _supply(tmp, "hidpp_battery_0", capacity="unknown")
            self.assertIsNone(battery(Path(tmp)))

    def test_an_unrelated_power_supply_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            _supply(tmp, "AC", capacity=99, status="Full")
            self.assertIsNone(battery(Path(tmp)))

    def test_the_label_is_a_percentage(self):
        self.assertEqual(Battery(capacity=85, charging=False).label, "85%")


class ModelNameTests(unittest.TestCase):
    def test_reads_the_model_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            _supply(tmp, "hidpp_battery_0", model_name="G502 LIGHTSPEED")
            self.assertEqual(model_name(Path(tmp)), "G502 LIGHTSPEED")

    def test_a_wired_mouse_has_no_model_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(model_name(Path(tmp)))

    def test_a_missing_sysfs_is_not_an_error(self):
        self.assertIsNone(model_name(Path("/nonexistent/power_supply")))


if __name__ == "__main__":
    unittest.main()