"""Tests for the hotspot editor and the binding editor.

Both build GTK widgets, so they need a display; the hotspot editor also draws
with cairo. They live apart from the window tests because they exercise
different modules: hotspot_editor.py and binding_editor.py.
"""

import unittest

from .support import has_cairo


@unittest.skipUnless(has_cairo(), "needs pycairo and Gtk 4")
class HotspotDrawingTests(unittest.TestCase):
    """Guards against stray ink between the hotspots.

    cairo's show_text() leaves a current point, so the next arc() draws a line
    from the previous label to the new circle. On screen that looked like lines
    tying the buttons together.
    """

    def _stray_between_circles(self) -> int:
        import cairo

        from linghub.ui.buttonmap import ButtonSpot
        from linghub.ui.assignments.diagram import HOTSPOT_RADIUS, MouseDiagram

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


@unittest.skipUnless(has_cairo(), "needs pycairo and Gtk 4")
class HitTestGeometryTests(unittest.TestCase):
    """The click target must sit where the circle is painted.

    The image is letterboxed to keep its aspect ratio, so it does not fill the
    widget. Drawing used the letterbox offsets while hit-testing used raw
    fractions of the widget, which put the targets up to 52 px away from the
    circles on a real window size - some buttons could not be clicked at all.
    """

    def _diagram(self, image_width: int, image_height: int):
        from linghub.ui.assignments.diagram import MouseDiagram

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
        from linghub.ui.assignments import diagram as diagram_module
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
        from linghub.ui.assignments.diagram import HOTSPOT_RADIUS

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


@unittest.skipUnless(has_cairo(), "needs pycairo and Gtk 4")
class HotspotEditorTests(unittest.TestCase):
    """The editor maps a click to a button, so redoing one point is possible.

    Points are keyed by ratbag index rather than by click order. Placing is
    explicit: a marker click always selects or drags, never restamps, which is
    what made moving one circle appear to move others.
    """

    def _editor(self, points=None):
        from linghub.tools.hotspot_editor import HotspotEditor

        editor = HotspotEditor.__new__(HotspotEditor)
        editor._points = dict(points or {})
        editor._selected = 0
        editor._hover = None
        editor._armed = False
        editor._drag = None
        editor._drag_origin = None
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

    # --- placing ------------------------------------------------------

    def test_placing_needs_the_button_to_be_armed(self):
        editor = self._editor()
        editor._selected = 5
        editor._to_fraction = lambda x, y: (0.25, 0.5)
        editor._on_pressed(_FakeGesture(1), 1, 100, 200)
        self.assertEqual(editor.points, {})
        self.assertEqual(editor._emitted[-1], ("needs-arm", 5))

    def test_armed_click_places_the_selected_button(self):
        editor = self._editor()
        editor.arm(5)
        editor._to_fraction = lambda x, y: (0.25, 0.5)
        editor._on_pressed(_FakeGesture(1), 1, 100, 200)
        self.assertEqual(editor.points, {5: (0.25, 0.5)})
        self.assertFalse(editor.armed)

    def test_placing_advances_to_the_next_unplaced_button(self):
        editor = self._editor()
        editor.arm(0)
        editor._to_fraction = lambda x, y: (0.2, 0.2)
        editor._on_pressed(_FakeGesture(1), 1, 10, 10)
        self.assertEqual(editor.selected, 1)

    def test_advance_skips_buttons_that_already_have_points(self):
        editor = self._editor({1: (0.5, 0.5)})
        editor.arm(0)
        editor._to_fraction = lambda x, y: (0.2, 0.2)
        editor._on_pressed(_FakeGesture(1), 1, 10, 10)
        self.assertEqual(editor.selected, 2)

    # --- the bug: clicking a marker must not move anything ------------

    def test_clicking_a_marker_selects_it_and_moves_nothing(self):
        editor = self._editor({7: (0.5, 0.5)})
        editor._selected = 0
        cx, cy = self._image_rect_centre(editor, 0.5, 0.5)
        editor._on_pressed(_FakeGesture(1), 1, cx, cy)
        self.assertEqual(editor.selected, 7)
        self.assertEqual(editor.points, {7: (0.5, 0.5)})

    def test_clicking_a_marker_does_not_restamp_even_when_armed(self):
        """The old bug: an armed button stamped itself onto the clicked marker."""
        editor = self._editor({7: (0.5, 0.5)})
        editor.arm(2)
        cx, cy = self._image_rect_centre(editor, 0.5, 0.5)
        editor._on_pressed(_FakeGesture(1), 1, cx, cy)
        self.assertEqual(editor.points, {7: (0.5, 0.5)})

    def test_clicking_empty_space_leaves_other_markers_alone(self):
        editor = self._editor({7: (0.5, 0.5), 8: (0.2, 0.2)})
        editor._to_fraction = lambda x, y: (0.9, 0.9)
        editor._on_pressed(_FakeGesture(1), 1, 900, 500)
        self.assertEqual(editor.points, {7: (0.5, 0.5), 8: (0.2, 0.2)})

    # --- dragging -----------------------------------------------------

    def test_drag_moves_only_the_dragged_marker(self):
        editor = self._editor({7: (0.5, 0.5), 8: (0.2, 0.2)})
        editor._on_drag_begin(_FakeGesture(1), *self._image_rect_centre(editor, 0.5, 0.5))
        self.assertEqual(editor._drag, 7)
        editor._on_drag_update(_FakeGesture(1), 102.4, 55.5)  # +10% of the width
        self.assertEqual(editor.points[8], (0.2, 0.2))
        self.assertAlmostEqual(editor.points[7][0], 0.6, places=3)
        self.assertAlmostEqual(editor.points[7][1], 0.6, places=3)

    def test_drag_offsets_are_relative_to_the_drag_origin(self):
        """A regression here makes the marker jump by the origin on each move."""
        editor = self._editor({3: (0.4, 0.4)})
        editor._on_drag_begin(_FakeGesture(1), *self._image_rect_centre(editor, 0.4, 0.4))
        editor._on_drag_update(_FakeGesture(1), 51.2, 0)
        editor._on_drag_update(_FakeGesture(1), 51.2, 0)
        # Both updates apply the same absolute offset, so the value is stable.
        self.assertAlmostEqual(editor.points[3][0], 0.45, places=3)

    def test_drag_outside_the_image_does_not_move_the_marker(self):
        editor = self._editor({3: (0.9, 0.9)})
        editor._on_drag_begin(_FakeGesture(1), *self._image_rect_centre(editor, 0.9, 0.9))
        editor._on_drag_update(_FakeGesture(1), 500, 500)
        self.assertEqual(editor.points[3], (0.9, 0.9))

    # --- removing -----------------------------------------------------

    def test_right_click_removes_the_marker_under_the_cursor(self):
        editor = self._editor({3: (0.5, 0.5)})
        cx, cy = self._image_rect_centre(editor, 0.5, 0.5)
        editor._on_pressed(_FakeGesture(3), 1, cx, cy)
        self.assertEqual(editor.points, {})

    def test_remove_ignores_buttons_that_have_no_point(self):
        editor = self._editor({3: (0.5, 0.5)})
        editor.remove(9)
        self.assertEqual(editor.points, {3: (0.5, 0.5)})

    def test_backspace_path_removes_the_selected_button(self):
        """The window used to mutate a copy, so Backspace did nothing."""
        editor = self._editor({0: (0.1, 0.1), 1: (0.2, 0.2)})
        editor.select(1)
        editor.remove(editor.selected)
        self.assertEqual(editor.points, {0: (0.1, 0.1)})

    # --- misc ---------------------------------------------------------

    def test_clicks_outside_the_image_are_ignored(self):
        editor = self._editor()
        editor.arm(0)
        editor._to_fraction = lambda x, y: None
        editor._on_pressed(_FakeGesture(1), 1, 0, 0)
        self.assertEqual(editor.points, {})

    def test_selecting_emits_only_on_change(self):
        editor = self._editor()
        editor.select(4)
        editor.select(4)
        self.assertEqual(len([e for e in editor._emitted if e[0] == "selection-changed"]), 1)

    def test_selecting_disarms(self):
        editor = self._editor()
        editor.arm(2)
        self.assertTrue(editor.armed)
        editor.select(5)
        self.assertFalse(editor.armed)

    def test_load_points_is_keyed_by_index(self):
        import json
        import tempfile
        from pathlib import Path

        from linghub.tools.hotspot_editor import load_points

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

        from linghub.tools.hotspot_editor import load_points

        self.assertEqual(load_points(Path("/nonexistent/hotspots.json")), {})

    @staticmethod
    def _image_rect_centre(editor, fx, fy):
        ox, oy, dw, dh = editor._image_rect()
        return ox + fx * dw, oy + fy * dh


@unittest.skipUnless(has_cairo(), "needs pycairo and Gtk 4")
class BindingEditorTests(unittest.TestCase):
    """Opening the dialog on an existing binding must not change it.

    If the initial value is not pre-selected, pressing Apply replaces the
    binding with whatever happened to be listed first - silently, and with no
    way to tell it happened.
    """

    CASES = [
        ("key", "KEY_SPACE"),
        ("key", "KEY_F"),
        ("special", "resolution-up"),
        ("special", "wheel-down"),
        ("button", "4"),
        ("button", "1"),
        ("macro", "+KEY_LEFTCTRL +KEY_C -KEY_C -KEY_LEFTCTRL"),
        ("macro", "KEY_M"),
        ("disabled", None),
    ]

    def _open(self, kind, value):
        from linghub.ui.assignments.editor import BindingEditor

        # Adw.Window needs an application, but the widget tree can be built
        # with a plain Gtk.Window parent.
        return BindingEditor(
            parent=None, button_index=3, kind=kind, value=value,
            on_apply=lambda i, k, v: True,
        )

    def test_every_type_round_trips_unchanged(self):
        for kind, value in self.CASES:
            with self.subTest(kind=kind, value=value):
                editor = self._open(kind, value)
                got_kind, got_value = editor._current_binding()
                self.assertEqual(got_kind, kind)
                if kind == "disabled":
                    self.assertIsNone(got_value)
                elif kind == "button":
                    self.assertEqual(int(got_value), int(value))
                else:
                    self.assertEqual(got_value, value)

    def test_mode_matches_the_binding_type(self):
        """A single-key macro is its own mode, not a chord."""
        expected = {
            "key": "key", "special": "special", "button": "button",
            "macro": "chord", "disabled": "nothing",
        }
        for kind, value in self.CASES:
            with self.subTest(kind=kind):
                mode = self._open(kind, value).mode
                if kind == "macro" and value == "KEY_M":
                    self.assertEqual(mode, "key-macro")
                else:
                    self.assertEqual(mode, expected[kind])

    def test_a_single_key_macro_opens_in_its_own_mode(self):
        """ACTION_MACRO with one press/release pair is a key sent the macro way.

        Some games only honour that form, so it must not be shown as a chord -
        re-saving would silently change the mechanism and break the binding.
        """
        editor = self._open("macro", "KEY_X")
        self.assertEqual(editor.mode, "key-macro")
        self.assertEqual(editor._current_binding(), ("macro", "KEY_X"))

    def test_a_single_key_macro_is_not_confused_with_a_key(self):
        editor = self._open("macro", "KEY_X")
        self.assertNotEqual(editor.mode, "key")

    def test_a_real_chord_still_opens_as_a_chord(self):
        editor = self._open("macro", "+KEY_LEFTCTRL +KEY_C -KEY_C -KEY_LEFTCTRL")
        self.assertEqual(editor.mode, "chord")

    def test_unknown_macro_key_is_kept(self):
        """A key outside the common list must not be silently dropped."""
        editor = self._open("macro", "+KEY_LEFTCTRL +KEY_KPENTER -KEY_KPENTER -KEY_LEFTCTRL")
        kind, value = editor._current_binding()
        self.assertEqual(kind, "macro")
        self.assertIn("KEY_KPENTER", value)
        self.assertIn("KEY_LEFTCTRL", value)


class _FakeGesture:
    def __init__(self, button):
        self._button = button

    def get_current_button(self):
        return self._button


if __name__ == "__main__":
    unittest.main()
