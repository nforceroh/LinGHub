"""Tests for the lighting panel's mapping between UI and hardware values.

The panel talks in speed; the hardware takes a duration in milliseconds. That
inversion is the easy thing to get backwards, and getting it backwards makes
"fast" mean "slow".
"""

import unittest

from linghub.ui.led_panel import (
    ANIMATED_MODES,
    DEFAULT_DURATION,
    MODES,
    LedPanel,
)


class ModeVocabularyTests(unittest.TestCase):
    def test_modes_match_the_hardware_enum(self):
        self.assertEqual(
            [name for name, _label in MODES],
            ["off", "on", "cycle", "breathing"],
        )

    def test_every_mode_has_a_label(self):
        for name, label in MODES:
            self.assertTrue(label.strip(), f"{name} has no label")

    def test_animated_modes_have_a_speed(self):
        self.assertEqual(set(ANIMATED_MODES), {"cycle", "breathing"})


class DurationMappingTests(unittest.TestCase):
    """The slider is a speed: higher means faster, so lower duration."""

    def test_speed_round_trips(self):
        for duration in (1000, 3000, 8000, 20000):
            speed = LedPanel._duration_to_speed(duration)
            self.assertAlmostEqual(
                LedPanel._speed_to_duration(speed), duration, delta=1200
            )

    def test_higher_speed_means_shorter_duration(self):
        slow = LedPanel._speed_to_duration(2)
        fast = LedPanel._speed_to_duration(18)
        self.assertLess(fast, slow)

    def test_speed_is_clamped_to_the_slider_range(self):
        self.assertEqual(LedPanel._duration_to_speed(1), 20)
        self.assertEqual(LedPanel._duration_to_speed(10_000_000), 1)

    def test_zero_duration_does_not_divide_by_zero(self):
        self.assertEqual(LedPanel._duration_to_speed(0), 10)

    def test_default_duration_is_within_range(self):
        speed = LedPanel._duration_to_speed(DEFAULT_DURATION)
        self.assertGreaterEqual(speed, 1)
        self.assertLessEqual(speed, 20)


if __name__ == "__main__":
    unittest.main()
