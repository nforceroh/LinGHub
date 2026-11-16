"""Tests for the UI's non-graphical logic.

The diagram and window need a display, so these cover the parts that do not:
the button map and the daemon client's message handling.
"""

import unittest
from types import SimpleNamespace

from dbus_fast import MessageType

from linghub.ui.buttonmap import (
    BUTTONS,
    BY_INDEX,
    MANUAL,
    describe,
    manual_number,
)
from linghub.ui.client import INTERFACE, DaemonClient


def _has_cairo() -> bool:
    try:
        import cairo  # noqa: F401
        import gi

        gi.require_version("Gtk", "4.0")
    except (ImportError, ValueError):
        return False
    return True


class ButtonMapTests(unittest.TestCase):
    def test_covers_every_ratbag_index(self):
        self.assertEqual(sorted(BY_INDEX), list(range(11)))

    def test_manual_numbers_are_one_to_eleven(self):
        self.assertEqual(sorted(MANUAL.values()), list(range(1, 12)))

    def test_manual_numbers_match_the_documented_map(self):
        """docs/button-map.md is the source of truth for this mapping.

        ratbag and the manual disagree on the tilt wheel and the profile
        button, which is exactly the sort of thing that silently rots.
        """
        self.assertEqual(MANUAL[10], 9)  # scroll left
        self.assertEqual(MANUAL[9], 10)  # scroll right
        self.assertEqual(MANUAL[8], 11)  # profile select
        self.assertEqual(MANUAL[0], 1)  # left click
        self.assertEqual(MANUAL[7], 8)  # last of the aligned run

    def test_manual_number_of_unknown_index(self):
        self.assertEqual(manual_number(99), "-")

    def test_positions_are_fractions(self):
        for spot in BUTTONS:
            self.assertGreaterEqual(spot.x, 0.0)
            self.assertLessEqual(spot.x, 1.0)
            self.assertGreaterEqual(spot.y, 0.0)
            self.assertLessEqual(spot.y, 1.0)

    def test_positions_are_distinct(self):
        """Two hotspots on the same spot would make one unclickable."""
        seen = set()
        for spot in BUTTONS:
            key = (round(spot.x, 3), round(spot.y, 3))
            self.assertNotIn(key, seen, f"duplicate position for button {spot.index}")
            seen.add(key)

    def test_describe_includes_g_name(self):
        self.assertEqual(describe(3), "Back (G4)")

    def test_describe_omits_empty_g_name(self):
        self.assertEqual(describe(0), "Left click")

    def test_describe_handles_unknown_index(self):
        self.assertEqual(describe(99), "Button 99")


class SignalHandlingTests(unittest.TestCase):
    def setUp(self):
        self.calls = 0
        self.client = DaemonClient()
        self.client.set_change_handler(self._bump)

    def _bump(self):
        self.calls += 1

    def _signal(self, interface=INTERFACE, member="ProfileChanged"):
        return SimpleNamespace(
            message_type=MessageType.SIGNAL, interface=interface, member=member, body=["x"]
        )

    def test_our_signal_triggers_change(self):
        self.client._handle_signal(self._signal())
        self.assertEqual(self.calls, 1)

    def test_other_interface_is_ignored(self):
        self.client._handle_signal(self._signal(interface="org.example.Other"))
        self.assertEqual(self.calls, 0)

    def test_method_return_is_ignored(self):
        message = SimpleNamespace(
            message_type=MessageType.METHOD_RETURN, interface=INTERFACE,
            member="ProfileChanged", body=["x"],
        )
        self.client._handle_signal(message)
        self.assertEqual(self.calls, 0)

    def test_no_handler_is_safe(self):
        client = DaemonClient()
        client._handle_signal(self._signal())  # must not raise


@unittest.skipUnless(_has_cairo(), "needs pycairo and Gtk 4")
class HotspotDrawingTests(unittest.TestCase):
    """Guards against stray ink between the hotspots.

    cairo's show_text() leaves a current point, so the next arc() draws a line
    from the previous label to the new circle. On screen that looked like lines
    tying the buttons together.
    """

    def _stray_between_circles(self) -> int:
        import cairo

        from linghub.ui.buttonmap import ButtonSpot
        from linghub.ui.diagram import HOTSPOT_RADIUS, MouseDiagram

        # _draw_hotspot touches no widget state, so build the object without
        # GTK: DrawingArea wants a display and this should run headless.
        diagram = MouseDiagram.__new__(MouseDiagram)
        diagram._selected = None
        diagram._hovered = None

        width = height = 300
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        cr = cairo.Context(surface)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        for cx, cy, index in ((60, 150, 0), (240, 150, 1)):
            spot = ButtonSpot(index, "x", "", cx / width, cy / height)
            diagram._draw_hotspot(cr, cx, cy, spot)
        surface.flush()

        data = bytes(surface.get_data())
        stride = surface.get_stride()

        # Sample the gap between the two circles, skipping the circles.
        low = 60 + int(HOTSPOT_RADIUS) + 3
        high = 240 - int(HOTSPOT_RADIUS) - 3
        return sum(
            1
            for x in range(low, high)
            for y in (149, 150, 151)
            if data[y * stride + x * 4 + 3] > 20
        )

    def test_no_stray_ink_between_hotspots(self):
        self.assertEqual(self._stray_between_circles(), 0)


if __name__ == "__main__":
    unittest.main()
