"""Tests for the DPI panel's staging behaviour.

Same rule as the lighting panel: edits must not reach the mouse until Save.
"""

import unittest

from linghub.ui.dpi_panel import MAX_DPI, MIN_DPI, DpiPanel


def _panel(saved=None):
    calls = []
    panel = DpiPanel(on_save=lambda *a: calls.append(a))
    panel._calls = calls
    panel.load(
        saved or [
            {"dpi": 400, "default": False, "disabled": False},
            {"dpi": 800, "default": True, "disabled": False},
            {"dpi": 1600, "default": False, "disabled": True},
        ],
        (125, 250, 500, 1000),
        1000,
    )
    return panel


class StagingTests(unittest.TestCase):
    def test_a_freshly_loaded_panel_is_clean(self):
        self.assertFalse(_panel().dirty)

    def test_changing_a_dpi_value_makes_it_dirty(self):
        panel = _panel()
        panel._rows[0]["spin"].set_value(1200)
        self.assertTrue(panel.dirty)

    def test_changing_the_report_rate_makes_it_dirty(self):
        panel = _panel()
        panel._rate.set_selected(1)  # 250 Hz
        self.assertTrue(panel.dirty)

    def test_edits_are_not_published_before_save(self):
        panel = _panel()
        panel._rows[0]["spin"].set_value(1200)
        self.assertEqual(panel._calls, [])

    def test_save_publishes_the_values(self):
        panel = _panel()
        panel._rows[0]["spin"].set_value(1200)
        panel._save()
        slots, rate = panel._calls[0]
        self.assertEqual(slots[0][0], 1200)
        self.assertEqual(rate, 1000)

    def test_revert_restores_the_saved_values(self):
        panel = _panel()
        panel._rows[0]["spin"].set_value(1200)
        panel.revert()
        self.assertEqual(panel._rows[0]["spin"].get_value(), 400)
        self.assertFalse(panel.dirty)

    def test_mark_saved_clears_dirty(self):
        panel = _panel()
        panel._rows[0]["spin"].set_value(1200)
        panel.mark_saved()
        self.assertFalse(panel.dirty)


class DefaultSlotTests(unittest.TestCase):
    def test_only_one_slot_can_be_the_default(self):
        """Two defaults would be ambiguous; the hardware honours one."""
        panel = _panel()
        panel._rows[0]["default"].set_active(True)
        actives = [row["default"].get_active() for row in panel._rows]
        self.assertEqual(actives, [True, False, False])

    def test_ticking_the_default_marks_the_panel_dirty(self):
        panel = _panel()
        panel._rows[2]["default"].set_active(True)
        self.assertTrue(panel.dirty)


class LoadTests(unittest.TestCase):
    def test_slots_are_created_for_every_resolution(self):
        self.assertEqual(len(_panel()._rows), 3)

    def test_report_rate_is_preselected(self):
        panel = _panel()
        self.assertEqual(panel._rates[panel._rate.get_selected()], 1000)

    def test_unknown_report_rate_leaves_the_selection_alone(self):
        panel = DpiPanel(on_save=lambda *a: None)
        panel.load([{"dpi": 800}], (125, 250), 1337)
        self.assertFalse(panel.dirty)

    def test_range_covers_the_g502(self):
        self.assertEqual(MIN_DPI, 100)
        self.assertGreaterEqual(MAX_DPI, 25600)


if __name__ == "__main__":
    unittest.main()
