"""A one-line DPI track: every slot as a draggable marker on a shared scale.

The five slot rows this replaces spent a row each on a number that is really a
position on a scale, and the scale is the thing a user reasons about ("800 is
here, 1600 is there"). One track shows all five at once, in the space of a
single row.

Two things the track cannot express, and where they live instead:

- An exact value. Dragging lands on a multiple of the step, so the number
  above each marker is a button that opens a popover with a spin button.
- Which slot is the default, and whether a slot is disabled. Both are in the
  same popover, because they are properties of one slot rather than of the
  scale.

Markers may share a position. Several slots at 800 is a legitimate setup (a
profile that pins every slot to one speed), so markers are drawn side by side
when they collide rather than on top of each other, and each stays grabbable.
"""

from __future__ import annotations

import math

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("PangoCairo", "1.0")

from gi.repository import Gdk, Gtk, Pango, PangoCairo

from . import panel_rules

# The range ratbagd accepts for a G502; read from the device where possible.
MIN_DPI = 100
MAX_DPI = 25600

# How far apart colliding markers are drawn, in pixels.
COLLISION_OFFSET = 14

# Vertical bands, top to bottom: the value labels, the track with its markers,
# then the scale ticks and their numbers. They must not overlap: a tick number
# sitting on a marker reads as that marker's value.
LABEL_BAND = 40
LABEL_ROW_HEIGHT = 16
MARKER_RADIUS = 7
TICK_BAND = 30
TRACK_INSET = 28


def position_of(dpi: int, width: int) -> float:
    """Where `dpi` sits on a track `width` pixels wide.

    Logarithmic, because DPI is perceived proportionally: the step from 400 to
    800 is the same size as 1600 to 3200. A linear scale would spend most of
    the track above 10000, where nobody sets a DPI.
    """
    span = math.log(MAX_DPI) - math.log(MIN_DPI)
    fraction = (math.log(max(dpi, MIN_DPI)) - math.log(MIN_DPI)) / span
    return TRACK_INSET + fraction * max(width - 2 * TRACK_INSET, 1)


def dpi_at(x: float, width: int) -> int:
    """The DPI under a track position, rounded to the nearest step."""
    usable = max(width - 2 * TRACK_INSET, 1)
    fraction = min(max((x - TRACK_INSET) / usable, 0.0), 1.0)
    span = math.log(MAX_DPI) - math.log(MIN_DPI)
    dpi = math.exp(math.log(MIN_DPI) + fraction * span)
    return panel_rules.snap_dpi(dpi)


def spread(positions: list[float]) -> list[float]:
    """Nudge markers that share a position so each one stays grabbable.

    Returns one x per marker, in the same order. Markers that collide are
    fanned out symmetrically around the shared position; a marker on its own
    is left exactly where it is.
    """
    result = list(positions)
    groups: dict[float, list[int]] = {}
    for index, x in enumerate(positions):
        groups.setdefault(round(x, 3), []).append(index)
    for x, members in groups.items():
        if len(members) == 1:
            continue
        middle = (len(members) - 1) / 2
        for order, index in enumerate(members):
            result[index] = x + (order - middle) * COLLISION_OFFSET
    return result


class DpiTrack(Gtk.DrawingArea):
    """Every DPI slot on one logarithmic scale, each marker draggable."""

    def __init__(self):
        super().__init__()
        self._slots: list[dict] = []
        self._dragging: int | None = None
        self._on_edited = None
        self.set_content_height(LABEL_BAND + 2 * MARKER_RADIUS + TICK_BAND)
        self.set_hexpand(True)
        self.set_draw_func(self._draw)

        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self.add_controller(drag)

        click = Gtk.GestureClick()
        click.connect("released", self._on_click)
        self.add_controller(click)

    # --- state -----------------------------------------------------------

    def set_slots(self, slots: list[dict]) -> None:
        """Replace the markers. Each slot is {dpi, default, disabled}."""
        self._slots = [dict(slot) for slot in slots]
        self.queue_draw()

    def slots(self) -> list[dict]:
        return [dict(slot) for slot in self._slots]

    def set_on_edited(self, callback) -> None:
        """Called after any change, so the panel can mark itself dirty."""
        self._on_edited = callback

    def _edited(self) -> None:
        if self._on_edited is not None:
            self._on_edited()

    # --- geometry --------------------------------------------------------

    def _positions(self) -> list[float]:
        width = self.get_width()
        return spread([position_of(slot["dpi"], width) for slot in self._slots])

    def _marker_at(self, x: float, y: float) -> int | None:
        """The marker under a point, or None.

        Both axes matter: without the vertical check a click on the tick
        numbers, or anywhere else in the widget, would grab whichever marker
        happened to be nearest horizontally. The vertical tolerance is generous
        because the value label above a marker is part of its target.
        """
        track_y = LABEL_BAND + MARKER_RADIUS
        if not (track_y - LABEL_BAND <= y <= track_y + MARKER_RADIUS + 8):
            return None
        best, best_distance = None, 18.0
        for index, marker_x in enumerate(self._positions()):
            distance = abs(marker_x - x)
            if distance < best_distance:
                best, best_distance = index, distance
        return best

    # --- drawing ---------------------------------------------------------

    def _draw(self, _area, cr, width: int, height: int) -> None:
        track_y = LABEL_BAND + MARKER_RADIUS
        self._draw_track(cr, width, track_y)
        self._draw_ticks(cr, width, track_y)
        positions = self._positions()
        rows = self._label_rows(cr, positions)
        for index, x in enumerate(positions):
            self._draw_marker(cr, index, x, track_y, rows[index])

    def _label_rows(self, cr, positions: list[float]) -> list[int]:
        """Which row each value label goes on, so no two labels overlap.

        Markers cluster at the low end of a log scale (100, 400, 800, 1000 are
        all in the first third), so their labels would print on top of each
        other. A label that would collide with one already placed moves up a
        row instead.
        """
        rows: list[int] = []
        occupied: list[list[tuple[float, float]]] = [[], []]
        for index, x in enumerate(positions):
            half = self._text_width(cr, str(self._slots[index]["dpi"]), 11) / 2
            span = (x - half - 3, x + half + 3)
            row = 0
            for candidate in (0, 1):
                if all(span[1] < other[0] or span[0] > other[1]
                       for other in occupied[candidate]):
                    row = candidate
                    break
            else:
                # Both rows are full at this position; the third label shares
                # the top row rather than being dropped.
                row = 0
            occupied[row].append(span)
            rows.append(row)
        return rows

    def _draw_track(self, cr, width: int, y: float) -> None:
        cr.set_line_width(2)
        cr.set_source_rgba(1, 1, 1, 0.18)
        cr.move_to(TRACK_INSET, y)
        cr.line_to(width - TRACK_INSET, y)
        cr.stroke()

    def _draw_ticks(self, cr, width: int, track_y: float) -> None:
        cr.set_source_rgba(1, 1, 1, 0.35)
        for dpi in panel_rules.TICK_DPI:
            x = position_of(dpi, width)
            cr.set_line_width(1)
            cr.move_to(x, track_y + MARKER_RADIUS + 2)
            cr.line_to(x, track_y + MARKER_RADIUS + 7)
            cr.stroke()
            self._text(
                cr, str(dpi), x,
                track_y + MARKER_RADIUS + 18,
                size=9, centre=True, alpha=0.55,
            )

    def _draw_marker(self, cr, index: int, x: float, track_y: float,
                     label_row: int = 0) -> None:
        slot = self._slots[index]
        disabled = bool(slot.get("disabled"))
        is_default = bool(slot.get("default"))

        # A disabled slot is drawn hollow and dimmed: it is still on the track
        # so it can be re-enabled, but it is not part of the mouse's cycle.
        alpha = 0.35 if disabled else 1.0
        cr.set_source_rgba(0.36, 0.62, 0.98, alpha)
        cr.arc(x, track_y, MARKER_RADIUS, 0, 2 * math.pi)
        if disabled:
            cr.set_line_width(2)
            cr.stroke()
        else:
            cr.fill()

        # The default slot is underlined, the same signal G HUB uses.
        label = str(slot["dpi"])
        label_y = (track_y - MARKER_RADIUS - 10
                   - label_row * LABEL_ROW_HEIGHT)
        self._text(cr, label, x, label_y, size=11, centre=True, bold=is_default)
        if is_default:
            text_width = self._text_width(cr, label, 11, bold=True)
            cr.set_source_rgba(0.36, 0.62, 0.98, 1.0)
            cr.set_line_width(2)
            cr.move_to(x - text_width / 2, label_y + 9)
            cr.line_to(x + text_width / 2, label_y + 9)
            cr.stroke()

    def _text(self, cr, text: str, x: float, y: float, *, size: int,
              centre: bool = False, bold: bool = False,
              alpha: float = 0.85) -> None:
        layout = self.create_pango_layout(text)
        layout.set_font_description(
            Pango.FontDescription(f"{'Bold ' if bold else ''}{size}")
        )
        text_width, text_height = layout.get_pixel_size()
        cr.set_source_rgba(1, 1, 1, alpha)
        cr.move_to(x - text_width / 2 if centre else x, y - text_height / 2)
        PangoCairo.show_layout(cr, layout)

    def _text_width(self, cr, text: str, size: int, *, bold: bool = False) -> float:
        layout = self.create_pango_layout(text)
        layout.set_font_description(
            Pango.FontDescription(f"{'Bold ' if bold else ''}{size}")
        )
        return layout.get_pixel_size()[0]

    # --- interaction -----------------------------------------------------

    def _on_drag_begin(self, _gesture, start_x: float, start_y: float) -> None:
        self._dragging = self._marker_at(start_x, start_y)

    def _on_drag_update(self, _gesture, offset_x: float, offset_y: float) -> None:
        if self._dragging is None:
            return
        start = self._positions()[self._dragging]
        self._slots[self._dragging]["dpi"] = dpi_at(start + offset_x, self.get_width())
        self.queue_draw()
        self._edited()

    def _on_drag_end(self, _gesture, offset_x: float, offset_y: float) -> None:
        self._dragging = None

    def _on_click(self, _gesture, presses: int, x: float, y: float) -> None:
        """A click without a drag opens the slot's popover."""
        if presses != 1:
            return
        index = self._marker_at(x, y)
        if index is None:
            return
        self._open_popover(index, x, y)

    def _open_popover(self, index: int, x: float, y: float) -> None:
        slot = self._slots[index]
        popover = Gtk.Popover()
        popover.set_parent(self)
        popover.set_pointing_to(Gdk.Rectangle(int(x) - 1, int(y) - 1, 2, 2))

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        box.set_margin_start(10)
        box.set_margin_end(10)

        heading = Gtk.Label(label=f"Slot {index + 1}", xalign=0)
        heading.add_css_class("heading")
        box.append(heading)

        spin_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        spin_row.append(Gtk.Label(label="DPI", xalign=0))
        spin = Gtk.SpinButton.new_with_range(MIN_DPI, MAX_DPI, 50)
        spin.set_value(slot["dpi"])
        spin.set_hexpand(True)
        spin_row.append(spin)
        box.append(spin_row)

        default = Gtk.CheckButton(label="Default")
        default.set_tooltip_text("The setting the mouse uses by default")
        default.set_active(bool(slot.get("default")))
        box.append(default)

        disabled = Gtk.CheckButton(label="Disabled")
        disabled.set_tooltip_text("Hidden from the mouse's DPI cycle")
        disabled.set_active(bool(slot.get("disabled")))
        box.append(disabled)

        def apply(*_args) -> None:
            self._slots[index]["dpi"] = int(spin.get_value())
            self._slots[index]["disabled"] = disabled.get_active()
            if default.get_active():
                # Only one slot may be the default: ratbagd honours a single
                # one, so ticking this clears the rest.
                for position, other in enumerate(self._slots):
                    other["default"] = position == index
            else:
                self._slots[index]["default"] = False
            self.queue_draw()
            self._edited()

        spin.connect("value-changed", apply)
        default.connect("toggled", apply)
        disabled.connect("toggled", apply)

        popover.set_child(box)
        popover.popup()
