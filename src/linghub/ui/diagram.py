"""The interactive G502 diagram.

Draws the annotated image and overlays a clickable hotspot per button. The
hotspots are drawn rather than baked into the image so they can highlight the
selected button and stay aligned at any size.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gdk, GdkPixbuf, GObject, Gtk

from .buttonmap import BUTTONS, ButtonSpot


HOTSPOT_RADIUS = 13.0


class MouseDiagram(Gtk.DrawingArea):
    """A clickable picture of the mouse.

    Emits `button-selected` with the ratbag index when a hotspot is clicked.
    """

    __gsignals__ = {
        "button-selected": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    }

    def __init__(self, image_path: str):
        super().__init__()
        self._surface, self._surface_data = self._load_surface(image_path)
        self._selected: int | None = None
        self._hovered: int | None = None

        self.set_content_width(560)
        self.set_content_height(304)
        self.set_hexpand(True)
        self.set_vexpand(True)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", self._on_leave)
        self.add_controller(motion)

        click = Gtk.GestureClick()
        click.connect("pressed", self._on_pressed)
        self.add_controller(click)

        self.set_draw_func(self._draw)

    def set_selected(self, index: int | None) -> None:
        self._selected = index
        self.queue_draw()

    def _spot_at(self, x: float, y: float) -> ButtonSpot | None:
        width = self.get_width()
        height = self.get_height()
        if width <= 0 or height <= 0:
            return None
        for spot in BUTTONS:
            cx, cy = spot.x * width, spot.y * height
            if (x - cx) ** 2 + (y - cy) ** 2 <= HOTSPOT_RADIUS ** 2:
                return spot
        return None

    def _on_motion(self, _controller, x, y) -> None:
        spot = self._spot_at(x, y)
        index = spot.index if spot else None
        if index != self._hovered:
            self._hovered = index
            self.set_cursor(
                Gdk.Cursor.new_from_name("pointer", None) if spot else None
            )
            self.queue_draw()

    def _on_leave(self, _controller) -> None:
        self._hovered = None
        self.set_cursor(None)
        self.queue_draw()

    def _on_pressed(self, _gesture, _n_press, x, y) -> None:
        spot = self._spot_at(x, y)
        if spot is not None:
            self.emit("button-selected", spot.index)

    @staticmethod
    def _load_surface(image_path: str):
        """Load the image into a cairo surface.

        Gdk.Texture.download() returns an empty buffer here, so the pixels are
        taken from a GdkPixbuf instead, which is reliable.
        """
        import cairo

        pixbuf = GdkPixbuf.Pixbuf.new_from_file(image_path)
        width, height = pixbuf.get_width(), pixbuf.get_height()
        stride = pixbuf.get_rowstride()
        data = bytearray(pixbuf.get_pixels())
        surface = cairo.ImageSurface.create_for_data(
            data, cairo.FORMAT_RGB24, width, height, stride
        )
        # cairo does not own the buffer, so the caller keeps a reference.
        return surface, data

    def _draw(self, _area, cr, width, height) -> None:
        # Fit the image while preserving its aspect ratio.
        tex_w = self._surface.get_width()
        tex_h = self._surface.get_height()
        scale = min(width / tex_w, height / tex_h)
        draw_w, draw_h = tex_w * scale, tex_h * scale
        offset_x = (width - draw_w) / 2
        offset_y = (height - draw_h) / 2

        cr.save()
        cr.translate(offset_x, offset_y)
        cr.scale(scale, scale)
        # Gdk.Texture is a GdkPaintable, not a cairo surface, so it must be
        # drawn through Gtk's snapshot API rather than cr.set_source_*.
        cr.restore()

        # Draw the image with a snapshot, then overlay hotspots in cairo.
        self._draw_texture(cr, offset_x, offset_y, draw_w, draw_h)

        for spot in BUTTONS:
            cx = offset_x + spot.x * draw_w
            cy = offset_y + spot.y * draw_h
            self._draw_hotspot(cr, cx, cy, spot)

    def _draw_texture(self, cr, x: float, y: float, w: float, h: float) -> None:
        """Paint the image surface scaled into the given rectangle."""
        if self._surface is None:
            return
        cr.save()
        cr.translate(x, y)
        cr.scale(w / self._surface.get_width(), h / self._surface.get_height())
        cr.set_source_surface(self._surface, 0, 0)
        cr.paint()
        cr.restore()

    def _draw_hotspot(self, cr, cx: float, cy: float, spot: ButtonSpot) -> None:
        selected = spot.index == self._selected
        hovered = spot.index == self._hovered

        if selected:
            fill = (0.13, 0.66, 0.88, 0.95)
            ring = (1.0, 1.0, 1.0, 1.0)
        elif hovered:
            fill = (0.13, 0.66, 0.88, 0.75)
            ring = (1.0, 1.0, 1.0, 0.9)
        else:
            fill = (0.10, 0.10, 0.12, 0.55)
            ring = (1.0, 1.0, 1.0, 0.55)

        cr.set_source_rgba(*fill)
        cr.arc(cx, cy, HOTSPOT_RADIUS, 0, 6.2832)
        cr.fill_preserve()
        cr.set_source_rgba(*ring)
        cr.set_line_width(2.0 if selected else 1.5)
        cr.stroke()

        label = str(spot.index)
        cr.set_source_rgba(1.0, 1.0, 1.0, 1.0)
        cr.select_font_face("Sans", 0, 1 if selected else 0)
        cr.set_font_size(12)
        extents = cr.text_extents(label)
        cr.move_to(cx - extents.width / 2 - extents.x_bearing,
                   cy - extents.height / 2 - extents.y_bearing)
        cr.show_text(label)
