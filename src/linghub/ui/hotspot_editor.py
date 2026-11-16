"""Interactive hotspot placement tool.

Loads a picture of the mouse, lets you click to place a numbered hotspot for
each button, and writes the result as fractions of the image size so the
diagram can scale.

Run it with:

    linghub hotspots --image images/g502_trans.png

Click to place buttons in order 0, 1, 2, … Right-click or Backspace removes
the last one. Ctrl+S saves. The output is written to
src/linghub/ui/hotspots.json by default.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, Gtk


DEFAULT_OUTPUT = Path(__file__).resolve().parent / "hotspots.json"
RADIUS = 16.0


class HotspotEditor(Gtk.DrawingArea):
    """Draws the image and lets the user place numbered points on it."""

    def __init__(self, image_path: Path, points: list[tuple[float, float]]):
        super().__init__()
        self._pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(image_path))
        self._points = list(points)
        self._hover: tuple[float, float] | None = None

        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_draw_func(self._draw)

        click = Gtk.GestureClick()
        click.set_button(0)
        click.connect("pressed", self._on_pressed)
        self.add_controller(click)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", lambda _c: self._set_hover(None))
        self.add_controller(motion)

    @property
    def points(self) -> list[tuple[float, float]]:
        return list(self._points)

    def undo(self) -> None:
        if self._points:
            self._points.pop()
            self.queue_draw()

    def clear(self) -> None:
        self._points.clear()
        self.queue_draw()

    def _image_rect(self) -> tuple[float, float, float, float]:
        """Where the image is drawn: (x, y, width, height)."""
        width = self.get_width()
        height = self.get_height()
        iw = self._pixbuf.get_width()
        ih = self._pixbuf.get_height()
        if width <= 0 or height <= 0:
            return 0.0, 0.0, 0.0, 0.0
        scale = min(width / iw, height / ih)
        dw, dh = iw * scale, ih * scale
        return (width - dw) / 2, (height - dh) / 2, dw, dh

    def _to_fraction(self, x: float, y: float) -> tuple[float, float] | None:
        ox, oy, dw, dh = self._image_rect()
        if dw <= 0 or dh <= 0:
            return None
        fx = (x - ox) / dw
        fy = (y - oy) / dh
        if not (0.0 <= fx <= 1.0 and 0.0 <= fy <= 1.0):
            return None
        return fx, fy

    def _on_pressed(self, _gesture, _n, x, y) -> None:
        button = _gesture.get_current_button()
        if button == 3:
            self.undo()
            return
        frac = self._to_fraction(x, y)
        if frac is not None:
            self._points.append(frac)
            self.queue_draw()

    def _on_motion(self, _controller, x, y) -> None:
        self._set_hover(self._to_fraction(x, y))

    def _set_hover(self, frac) -> None:
        if frac != self._hover:
            self._hover = frac
            self.queue_draw()

    def _draw(self, _area, cr, width, height) -> None:
        ox, oy, dw, dh = self._image_rect()
        if dw <= 0:
            return

        cr.save()
        cr.translate(ox, oy)
        cr.scale(dw / self._pixbuf.get_width(), dh / self._pixbuf.get_height())
        Gdk.cairo_set_source_pixbuf(cr, self._pixbuf, 0, 0)
        cr.paint()
        cr.restore()

        for index, (fx, fy) in enumerate(self._points):
            self._draw_marker(cr, ox + fx * dw, oy + fy * dh, index, selected=False)

        if self._hover is not None:
            hx, hy = self._hover
            self._draw_marker(cr, ox + hx * dw, oy + hy * dh, len(self._points), selected=True)

    def _draw_marker(self, cr, cx: float, cy: float, index: int, selected: bool) -> None:
        if selected:
            cr.set_source_rgba(0.13, 0.66, 0.88, 0.45)
            cr.set_line_width(2.0)
        else:
            cr.set_source_rgba(0.13, 0.66, 0.88, 0.95)
            cr.set_line_width(2.5)
        # new_sub_path() is required: show_text() below leaves a current
        # point, and arc() would otherwise draw a line from it to this circle.
        cr.new_sub_path()
        cr.arc(cx, cy, RADIUS, 0, 6.2832)
        cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, 0.95)
        cr.stroke()

        label = str(index)
        cr.set_source_rgba(1, 1, 1, 1)
        cr.select_font_face("Sans", 0, 1)
        cr.set_font_size(14)
        ext = cr.text_extents(label)
        cr.move_to(cx - ext.width / 2 - ext.x_bearing, cy - ext.height / 2 - ext.y_bearing)
        cr.show_text(label)


class EditorWindow(Adw.ApplicationWindow):
    def __init__(self, app, image_path: Path, output: Path, points):
        super().__init__(application=app, title="LinGHub hotspot editor")
        self._output = output
        self.set_default_size(1200, 700)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self._title = Adw.WindowTitle(title="Hotspot editor", subtitle=image_path.name)
        header.set_title_widget(self._title)

        save = Gtk.Button(label="Save")
        save.add_css_class("suggested-action")
        save.connect("clicked", self._on_save)
        header.pack_end(save)

        undo = Gtk.Button(icon_name="edit-undo-symbolic")
        undo.set_tooltip_text("Remove the last hotspot")
        undo.connect("clicked", lambda _b: self._editor.undo())
        header.pack_start(undo)

        clear = Gtk.Button(icon_name="edit-clear-all-symbolic")
        clear.set_tooltip_text("Remove every hotspot")
        clear.connect("clicked", lambda _b: self._editor.clear())
        header.pack_start(clear)

        toolbar.add_top_bar(header)

        self._editor = HotspotEditor(image_path, points)
        toolbar.set_content(self._editor)
        self.set_content(toolbar)

        self._status = Gtk.Label()
        self._status.add_css_class("dim-label")
        toolbar.add_bottom_bar(self._status)
        self._update_status()

        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key)
        self.add_controller(key)

        GLib.timeout_add(300, self._tick)

    def _tick(self) -> bool:
        self._update_status()
        return GLib.SOURCE_CONTINUE

    def _update_status(self) -> None:
        count = len(self._editor.points)
        self._status.set_text(
            f"{count} hotspot(s) placed · click to add · right-click or Backspace to undo · Ctrl+S to save"
        )

    def _on_key(self, _c, keyval, _code, _mods) -> bool:
        if keyval == Gdk.KEY_BackSpace:
            self._editor.undo()
            return True
        if keyval in (Gdk.KEY_s, Gdk.KEY_S) and _mods & Gdk.ModifierType.CONTROL_MASK:
            self._on_save(None)
            return True
        return False

    def _on_save(self, _button) -> None:
        points = self._editor.points
        payload = {
            "image": "images/g502_trans.png",
            "hotspots": [
                {"index": i, "x": round(x, 4), "y": round(y, 4)}
                for i, (x, y) in enumerate(points)
            ],
        }
        self._output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        self._status.set_text(f"Saved {len(points)} hotspot(s) to {self._output}")


class EditorApp(Adw.Application):
    def __init__(self, image_path: Path, output: Path, points):
        super().__init__(application_id="org.linghub.HotspotEditor",
                         flags=Gio.ApplicationFlags.NON_UNIQUE)
        self._image_path = image_path
        self._output = output
        self._points = points

    def do_activate(self) -> None:
        EditorWindow(self, self._image_path, self._output, self._points).present()


def load_points(path: Path) -> list[tuple[float, float]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [(h["x"], h["y"]) for h in data.get("hotspots", [])]


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Place button hotspots on a mouse image.")
    parser.add_argument("--image", default="images/g502_trans.png", help="image to annotate")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="where to write the hotspots")
    args = parser.parse_args(argv)

    image_path = Path(args.image).resolve()
    if not image_path.exists():
        print(f"Error: image not found: {image_path}", file=sys.stderr)
        return 1

    output = Path(args.out).resolve()
    app = EditorApp(image_path, output, load_points(output))
    return app.run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
