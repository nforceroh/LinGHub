"""Tests for the DPI track's geometry.

The track is a drawing area, so its arithmetic is the part worth testing: a
marker that lands in the wrong place, or two markers that cannot be told
apart, are bugs no amount of clicking would make obvious.
"""

import unittest

from linghub.ui.dpi_track import (
    COLLISION_OFFSET,
    LABEL_BAND,
    MARKER_RADIUS,
    MAX_DPI,
    MIN_DPI,
    TRACK_INSET,
    DpiTrack,
    dpi_at,
    position_of,
    spread,
)


class PositionTests(unittest.TestCase):
    def test_the_range_ends_are_inset_from_the_edges(self):
        self.assertAlmostEqual(position_of(MIN_DPI, 400), TRACK_INSET)
        self.assertAlmostEqual(position_of(MAX_DPI, 400), 400 - TRACK_INSET)

    def test_a_higher_dpi_sits_further_right(self):
        positions = [position_of(dpi, 400) for dpi in (100, 800, 3200, 25600)]
        self.assertEqual(positions, sorted(positions))

    def test_the_scale_is_logarithmic(self):
        """Doubling the DPI moves the marker the same distance every time.

        This is the whole reason for a log scale: 400->800 and 1600->3200 are
        the same perceptual step, so they must be the same distance apart.
        """
        first = position_of(800, 400) - position_of(400, 400)
        second = position_of(3200, 400) - position_of(1600, 400)
        self.assertAlmostEqual(first, second, places=6)

    def test_a_linear_scale_would_crowd_the_low_end(self):
        """Guards the choice: on a linear scale 800 would sit at 3% of the way."""
        linear = (800 - MIN_DPI) / (MAX_DPI - MIN_DPI)
        self.assertLess(linear, 0.05)
        logarithmic = (position_of(800, 400) - TRACK_INSET) / (400 - 2 * TRACK_INSET)
        self.assertGreater(logarithmic, 0.2)


class DpiAtTests(unittest.TestCase):
    def test_the_ends_round_trip(self):
        self.assertEqual(dpi_at(TRACK_INSET, 400), MIN_DPI)
        self.assertEqual(dpi_at(400 - TRACK_INSET, 400), MAX_DPI)

    def test_a_position_round_trips_through_the_scale(self):
        for dpi in (100, 400, 800, 1600, 3200, 6400, 25600):
            self.assertEqual(dpi_at(position_of(dpi, 400), 400), dpi)

    def test_a_drag_past_the_end_is_clamped(self):
        self.assertEqual(dpi_at(-500, 400), MIN_DPI)
        self.assertEqual(dpi_at(5000, 400), MAX_DPI)

    def test_values_snap_to_the_step(self):
        """A drag must not produce 1237, which nobody would type."""
        self.assertEqual(dpi_at(position_of(1237, 400), 400), 1250)


class SpreadTests(unittest.TestCase):
    def test_distinct_markers_are_left_alone(self):
        self.assertEqual(spread([10.0, 50.0, 90.0]), [10.0, 50.0, 90.0])

    def test_colliding_markers_are_fanned_out(self):
        """Five slots at 800 is a legitimate setup, so all five must be grabbable."""
        result = spread([100.0, 100.0, 100.0, 100.0, 100.0])
        self.assertEqual(len(set(result)), 5)
        self.assertEqual(result[2], 100.0, "the middle marker stays put")

    def test_the_fan_is_symmetric_around_the_shared_position(self):
        result = spread([100.0, 100.0, 100.0])
        self.assertAlmostEqual(result[0], 100.0 - COLLISION_OFFSET)
        self.assertAlmostEqual(result[1], 100.0)
        self.assertAlmostEqual(result[2], 100.0 + COLLISION_OFFSET)

    def test_a_pair_straddles_the_position(self):
        result = spread([100.0, 100.0])
        self.assertAlmostEqual(result[0], 100.0 - COLLISION_OFFSET / 2)
        self.assertAlmostEqual(result[1], 100.0 + COLLISION_OFFSET / 2)

    def test_only_the_colliding_group_moves(self):
        result = spread([10.0, 100.0, 100.0, 200.0])
        self.assertEqual(result[0], 10.0)
        self.assertEqual(result[3], 200.0)


class HitTestTests(unittest.TestCase):
    """Which marker a click lands on.

    Needs a realised widget, because the positions depend on its width.
    """

    def _track(self, slots):
        from .support import has_cairo

        if not has_cairo():
            self.skipTest("needs pycairo and Gtk 4")
        import gi

        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk

        window = Gtk.Window()
        track = DpiTrack()
        track.set_slots(slots)
        window.set_child(track)
        window.set_default_size(900, 120)
        window.present()
        from gi.repository import GLib

        context = GLib.MainContext.default()
        for _ in range(80):
            context.iteration(False)
        return track

    def test_every_colliding_marker_is_individually_reachable(self):
        """Five slots at one DPI must still be five grabbable markers."""
        track = self._track(
            [{"dpi": 800, "default": False, "disabled": False}] * 5
        )
        track_y = LABEL_BAND + MARKER_RADIUS
        found = [
            track._marker_at(x, track_y) for x in track._positions()
        ]
        self.assertEqual(found, [0, 1, 2, 3, 4])

    def test_a_click_below_the_track_hits_nothing(self):
        """Otherwise a click on the tick numbers would grab a marker."""
        track = self._track([{"dpi": 800, "default": False, "disabled": False}])
        x = track._positions()[0]
        self.assertIsNone(track._marker_at(x, 400))

    def test_a_click_far_to_the_side_hits_nothing(self):
        track = self._track([{"dpi": 800, "default": False, "disabled": False}])
        track_y = LABEL_BAND + MARKER_RADIUS
        self.assertIsNone(track._marker_at(5, track_y))


if __name__ == "__main__":
    unittest.main()
