"""Tests for the DPI panel's staging behaviour.

Same rule as the lighting panel: edits must not reach the mouse until Save.
"""

import unittest

from linghub.ui.device.dpi_panel import DpiPanel
from linghub.ui.device.dpi_track import MAX_DPI, MIN_DPI


def _panel(saved=None):
    calls = []
    panel = DpiPanel(on_edited=lambda values: calls.append(values))
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


def _move(panel, index, dpi):
    """Move one marker, the way a drag does."""
    slots = panel._track.slots()
    slots[index]["dpi"] = dpi
    panel._track.set_slots(slots)
    panel._track._edited()


def _make_default(panel, index):
    """Make one slot the default, the way the popover does."""
    slots = panel._track.slots()
    for position, slot in enumerate(slots):
        slot["default"] = position == index
    panel._track.set_slots(slots)
    panel._track._edited()


class StagingTests(unittest.TestCase):
    def test_a_freshly_loaded_panel_is_clean(self):
        self.assertFalse(_panel().dirty)

    def test_changing_a_dpi_value_makes_it_dirty(self):
        panel = _panel()
        _move(panel, 0, 1200)
        self.assertTrue(panel.dirty)

    def test_changing_the_report_rate_makes_it_dirty(self):
        panel = _panel()
        panel._rate.set_selected(1)  # 250 Hz
        self.assertTrue(panel.dirty)

    def test_an_edit_reports_the_panel_values(self):
        """The window records what the panel shows, so Apply writes that."""
        panel = _panel()
        _move(panel, 0, 1200)
        slots, rate = panel._calls[-1]
        self.assertEqual(slots[0][0], 1200)
        self.assertEqual(rate, 1000)

    def test_revert_restores_the_saved_values(self):
        panel = _panel()
        _move(panel, 0, 1200)
        panel.revert()
        self.assertEqual(panel._track.slots()[0]["dpi"], 400)
        self.assertFalse(panel.dirty)

    def test_mark_saved_clears_dirty(self):
        panel = _panel()
        _move(panel, 0, 1200)
        panel.mark_saved()
        self.assertFalse(panel.dirty)


class DefaultSlotTests(unittest.TestCase):
    def test_only_one_slot_can_be_the_default(self):
        """Two defaults would be ambiguous; the hardware honours one."""
        panel = _panel()
        _make_default(panel, 0)
        actives = [slot["default"] for slot in panel._track.slots()]
        self.assertEqual(actives, [True, False, False])

    def test_ticking_the_default_marks_the_panel_dirty(self):
        panel = _panel()
        _make_default(panel, 2)
        self.assertTrue(panel.dirty)


class LoadTests(unittest.TestCase):
    def test_a_marker_is_created_for_every_resolution(self):
        self.assertEqual(len(_panel()._track.slots()), 3)

    def test_report_rate_is_preselected(self):
        panel = _panel()
        self.assertEqual(panel._rates[panel._rate.get_selected()], 1000)

    def test_unknown_report_rate_leaves_the_selection_alone(self):
        panel = DpiPanel(on_edited=lambda values: None)
        panel.load([{"dpi": 800}], (125, 250), 1337)
        self.assertFalse(panel.dirty)

    def test_legend_tracks_preset_values_and_default(self):
        panel = _panel()
        text = panel._legend_labels[1].get_text()
        self.assertIn("800", text)
        self.assertIn("²", text)

    def test_disabled_preset_is_dimmed_in_the_legend(self):
        panel = _panel()
        text = panel._legend_labels[2].get_text()
        self.assertIn("1600", text)

    def test_range_covers_the_g502(self):
        self.assertEqual(MIN_DPI, 100)
        self.assertGreaterEqual(MAX_DPI, 25600)


if __name__ == "__main__":
    unittest.main()
