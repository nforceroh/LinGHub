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


@unittest.skipUnless(_has_cairo(), "needs pycairo and Gtk 4")
class HitTestGeometryTests(unittest.TestCase):
    """The click target must sit where the circle is painted.

    The image is letterboxed to keep its aspect ratio, so it does not fill the
    widget. Drawing used the letterbox offsets while hit-testing used raw
    fractions of the widget, which put the targets up to 52 px away from the
    circles on a real window size - some buttons could not be clicked at all.
    """

    def _diagram(self, image_width: int, image_height: int):
        from linghub.ui.diagram import MouseDiagram

        diagram = MouseDiagram.__new__(MouseDiagram)
        diagram._selected = None
        diagram._hovered = None

        class Surface:
            def get_width(self):
                return image_width

            def get_height(self):
                return image_height

        diagram._surface = Surface()
        return diagram

    def test_centre_matches_the_letterboxed_draw_position(self):
        from linghub.ui.buttonmap import BUTTONS
        from linghub.ui.diagram import MouseDiagram

        # Deliberately taller than the image's aspect ratio, so there is
        # letterboxing to get wrong.
        width, height = 566, 486
        diagram = self._diagram(1024, 555)
        offset_x, offset_y, draw_w, draw_h = diagram._layout(width, height)

        for spot in BUTTONS:
            cx, cy = diagram._centre(spot, width, height)
            self.assertAlmostEqual(cx, offset_x + spot.x * draw_w)
            self.assertAlmostEqual(cy, offset_y + spot.y * draw_h)

        # The offsets must be real, otherwise this test proves nothing.
        self.assertGreater(offset_y, 0)

    def test_click_at_the_circle_selects_the_button(self):
        """Clicking exactly on a painted circle must select it."""
        from linghub.ui import diagram as diagram_module
        from linghub.ui.buttonmap import BUTTONS

        width, height = 566, 486
        widget = self._diagram(1024, 555)
        widget.get_width = lambda: width
        widget.get_height = lambda: height

        for spot in BUTTONS:
            cx, cy = widget._centre(spot, width, height)
            found = widget._spot_at(cx, cy)
            self.assertIsNotNone(found, f"button {spot.index} is not clickable")
            self.assertEqual(found.index, spot.index)
        self.assertTrue(hasattr(diagram_module, "HIT_RADIUS"))

    def test_click_just_off_the_circle_still_selects(self):
        """The target is larger than the drawn circle, within reason."""
        from linghub.ui.buttonmap import BUTTONS
        from linghub.ui.diagram import HOTSPOT_RADIUS

        width, height = 566, 486
        widget = self._diagram(1024, 555)
        widget.get_width = lambda: width
        widget.get_height = lambda: height

        spot = BUTTONS[0]
        cx, cy = widget._centre(spot, width, height)
        beyond = cx + HOTSPOT_RADIUS + 4
        found = widget._spot_at(beyond, cy)
        self.assertIsNotNone(found)
        self.assertEqual(found.index, spot.index)

    def test_click_far_away_selects_nothing(self):
        width, height = 566, 486
        widget = self._diagram(1024, 555)
        widget.get_width = lambda: width
        widget.get_height = lambda: height
        self.assertIsNone(widget._spot_at(1, 1))

    def test_no_size_is_safe(self):
        widget = self._diagram(1024, 555)
        widget.get_width = lambda: 0
        widget.get_height = lambda: 0
        self.assertIsNone(widget._spot_at(0, 0))


@unittest.skipUnless(_has_cairo(), "needs pycairo and Gtk 4")
class HotspotEditorTests(unittest.TestCase):
    """The editor maps a click to a button, so redoing one point is possible.

    Points are keyed by ratbag index rather than by click order: placing a
    point for a button that already has one moves it, which is what makes
    fixing a single bad hotspot practical.
    """

    def _editor(self, points=None):
        from linghub.ui.hotspot_editor import HotspotEditor

        editor = HotspotEditor.__new__(HotspotEditor)
        editor._points = dict(points or {})
        editor._selected = 0
        editor._hover = None
        emitted = []
        editor.emit = lambda *args: emitted.append(args)
        editor.queue_draw = lambda: None
        editor._emitted = emitted

        class Pixbuf:
            def get_width(self):
                return 1024

            def get_height(self):
                return 555

        editor._pixbuf = Pixbuf()
        # An image that fills the widget exactly, so fractions map 1:1.
        editor.get_width = lambda: 1024
        editor.get_height = lambda: 555
        return editor

    def test_placing_a_point_keys_it_to_the_selected_button(self):
        editor = self._editor()
        editor._selected = 5
        editor._to_fraction = lambda x, y: (0.25, 0.5)
        editor._on_pressed(_FakeGesture(1), 1, 100, 200)
        self.assertEqual(editor.points, {5: (0.25, 0.5)})

    def test_replacing_an_existing_point_does_not_add_a_second(self):
        editor = self._editor({5: (0.1, 0.1)})
        editor._selected = 5
        editor._to_fraction = lambda x, y: (0.9, 0.9)
        editor._on_pressed(_FakeGesture(1), 1, 100, 200)
        self.assertEqual(editor.points, {5: (0.9, 0.9)})

    def test_placing_advances_to_the_next_unplaced_button(self):
        editor = self._editor()
        editor._selected = 0
        editor._to_fraction = lambda x, y: (0.2, 0.2)
        editor._on_pressed(_FakeGesture(1), 1, 10, 10)
        self.assertEqual(editor.selected, 1)

    def test_advance_skips_buttons_that_already_have_points(self):
        editor = self._editor({1: (0.5, 0.5)})
        editor._selected = 0
        editor._to_fraction = lambda x, y: (0.2, 0.2)
        editor._on_pressed(_FakeGesture(1), 1, 10, 10)
        self.assertEqual(editor.selected, 2)

    def test_clicking_an_existing_marker_selects_it(self):
        editor = self._editor({7: (0.5, 0.5)})
        editor._selected = 0
        cx, cy = editor._image_rect()[0] + 0.5 * 1024, 0.5 * 555
        editor._on_pressed(_FakeGesture(1), 1, cx, cy)
        self.assertEqual(editor.selected, 7)
        self.assertEqual(editor.points, {7: (0.5, 0.5)})

    def test_right_click_removes_the_marker_under_the_cursor(self):
        editor = self._editor({3: (0.5, 0.5)})
        cx = editor._image_rect()[0] + 0.5 * 1024
        cy = editor._image_rect()[1] + 0.5 * 555
        editor._on_pressed(_FakeGesture(3), 1, cx, cy)
        self.assertEqual(editor.points, {})

    def test_clicks_outside_the_image_are_ignored(self):
        editor = self._editor()
        editor._to_fraction = lambda x, y: None
        editor._on_pressed(_FakeGesture(1), 1, 0, 0)
        self.assertEqual(editor.points, {})

    def test_selecting_emits_only_on_change(self):
        editor = self._editor()
        editor.select(4)
        editor.select(4)
        self.assertEqual(len(editor._emitted), 1)

    def test_load_points_is_keyed_by_index(self):
        import json
        import tempfile
        from pathlib import Path

        from linghub.ui.hotspot_editor import load_points

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hotspots.json"
            path.write_text(json.dumps({
                "image": "x.png",
                "hotspots": [
                    {"index": 0, "x": 0.1, "y": 0.2},
                    {"index": 9, "x": 0.3, "y": 0.4},
                ],
            }))
            self.assertEqual(load_points(path), {0: (0.1, 0.2), 9: (0.3, 0.4)})

    def test_load_points_tolerates_a_missing_file(self):
        from pathlib import Path

        from linghub.ui.hotspot_editor import load_points

        self.assertEqual(load_points(Path("/nonexistent/hotspots.json")), {})


class _FakeGesture:
    def __init__(self, button):
        self._button = button

    def get_current_button(self):
        return self._button


if __name__ == "__main__":
    unittest.main()
