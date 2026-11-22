"""Tests for the lighting panel's widget behaviour.

The vocabulary and the duration-to-speed arithmetic moved into `panel_rules`
when they were lifted out of the GTK callbacks; those tests live in
`test_panel_rules.py`. What remains here needs the widget: staging edits,
dirty tracking, and that nothing is published before Save.
"""

import unittest

from linghub.ui.device.led_panel import MODES, LedPanel


class DirtyStateTests(unittest.TestCase):
    """Nothing reaches the mouse until Save, so the panel must track edits.

    Previously every slider pixel fired a write, so 20 steps of a drag meant 20
    config writes and 40 hardware commits.
    """

    def _panel(self):
        from linghub.ui.device.led_panel import LedPanel

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
        from linghub.ui.device.led_panel import LedPanel

        panel = LedPanel(on_save=lambda *a: calls.append(a))
        panel.load({
            0: {"mode": "on", "color": (255, 0, 0), "brightness": 100, "duration": 0},
        })
        calls.clear()
        for value in range(100, 121):
            panel._brightness.set_value(value)
        self.assertEqual(calls, [])


class EffectControlTests(unittest.TestCase):
    def test_four_effect_options_are_available(self):
        panel = LedPanel(on_save=lambda *a: None)
        self.assertEqual(
            [label for _name, label in MODES],
            ["Off", "Fixed colour", "Cycle colours", "Breathing"],
        )
        self.assertEqual(panel._mode.get_selected(), 1)

    def test_selecting_cycle_updates_the_panel_mode(self):
        panel = LedPanel(on_save=lambda *a: None)
        panel._mode.set_selected(2)
        self.assertEqual(panel.mode, "cycle")

    def test_rate_and_brightness_values_update_as_labels(self):
        panel = LedPanel(on_save=lambda *a: None)
        panel.load({
            0: {
                "mode": "on",
                "color": (10, 20, 30),
                "brightness": 100,
                "duration": 5000,
            },
        })
        panel._brightness.set_value(180)
        panel._speed.set_value(10)
        self.assertEqual(panel._brightness_value.get_text(), "180")
        self.assertEqual(panel._speed_value.get_text(), "2000ms")


if __name__ == "__main__":
    unittest.main()
