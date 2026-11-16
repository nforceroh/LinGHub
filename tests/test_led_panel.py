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


class DirtyStateTests(unittest.TestCase):
    """Nothing reaches the mouse until Save, so the panel must track edits.

    Previously every slider pixel fired a write, so 20 steps of a drag meant 20
    config writes and 40 hardware commits.
    """

    def _panel(self):
        from linghub.ui.led_panel import LedPanel

        panel = LedPanel(on_save=lambda *a: None)
        panel.load({
            0: {"mode": "on", "color": (255, 0, 0), "brightness": 100, "duration": 0},
            1: {"mode": "on", "color": (255, 0, 0), "brightness": 100, "duration": 0},
        })
        return panel

    def test_a_freshly_loaded_panel_is_not_dirty(self):
        self.assertFalse(self._panel().dirty)

    def test_changing_brightness_makes_it_dirty(self):
        panel = self._panel()
        panel._brightness.set_value(200)
        self.assertTrue(panel.dirty)

    def test_changing_the_mode_makes_it_dirty(self):
        panel = self._panel()
        panel._mode.set_selected(2)  # cycle
        self.assertTrue(panel.dirty)

    def test_reverting_clears_dirty(self):
        panel = self._panel()
        panel._brightness.set_value(200)
        panel.revert()
        self.assertFalse(panel.dirty)

    def test_revert_restores_the_saved_values(self):
        panel = self._panel()
        panel._brightness.set_value(200)
        panel.revert()
        self.assertEqual(panel.brightness, 100)

    def test_saved_resets_the_baseline(self):
        panel = self._panel()
        panel._brightness.set_value(200)
        panel.mark_saved()
        self.assertFalse(panel.dirty)
        panel._brightness.set_value(150)
        self.assertTrue(panel.dirty)

    def test_edits_are_not_published_before_save(self):
        """The whole point: dragging must not write to the daemon."""
        calls = []
        from linghub.ui.led_panel import LedPanel

        panel = LedPanel(on_save=lambda *a: calls.append(a))
        panel.load({
            0: {"mode": "on", "color": (255, 0, 0), "brightness": 100, "duration": 0},
        })
        calls.clear()
        for value in range(100, 121):
            panel._brightness.set_value(value)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
