"""Interactive hotspot placement tool.

Loads a picture of the mouse, lets you click to place a numbered hotspot for
each button, and writes the result as fractions of the image size so the
diagram can scale.

Run it with:

    linghub hotspots

It opens with the current hotspots loaded. Pick a button in the list on the
right, then click the picture where that button is. Placing a point for a
button that already has one moves it, so you can redo individual buttons
rather than all eleven. Points are highlighted as selected, hovered, or
already placed.

Right-click a marker to remove it. Ctrl+S saves; the output is
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

from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, GObject, Gtk

from .buttonmap import BY_INDEX, NAMES, describe, manual_number


DEFAULT_OUTPUT = Path(__file__).resolve().parent / "hotspots.json"
RADIUS = 16.0


class HotspotEditor(Gtk.DrawingArea):
    """Draws the image and lets the user place numbered points on it."""

    __gsignals__ = {
        "selection-changed": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        "points-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, image_path: Path, points: dict[int, tuple[float, float]]):
        super().__init__()
        self._pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(image_path))
        # Keyed by ratbag index so a point stays attached to its button no
        # matter what order they are placed in.
        self._points: dict[int, tuple[float, float]] = dict(points)
        self._selected: int = NAMES[0][0]
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
    def points(self) -> dict[int, tuple[float, float]]:
        return dict(self._points)

    @property
    def selected(self) -> int:
        return self._selected

    def select(self, index: int) -> None:
        if index != self._selected:
            self._selected = index
            self.emit("selection-changed", index)
            self.queue_draw()

    def next_unplaced(self) -> None:
        """Select the first button that has no point yet, if any."""
        for index, _name, _g in NAMES:
            if index not in self._points:
                self.select(index)
                return

    def clear(self) -> None:
        self._points.clear()
        self.emit("points-changed")
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

    def _marker_at(self, x: float, y: float) -> int | None:
        """The ratbag index of the marker under the cursor, if any."""
        ox, oy, dw, dh = self._image_rect()
        if dw <= 0 or dh <= 0:
            return None
        best: int | None = None
        best_distance = RADIUS ** 2
        for index, (fx, fy) in self._points.items():
            cx, cy = ox + fx * dw, oy + fy * dh
            distance = (x - cx) ** 2 + (y - cy) ** 2
            if distance <= best_distance:
                best, best_distance = index, distance
        return best

    def _on_pressed(self, _gesture, _n, x, y) -> None:
        button = _gesture.get_current_button()
        if button == 3:
            index = self._marker_at(x, y)
            if index is not None:
                del self._points[index]
                self.emit("points-changed")
                self.queue_draw()
            return

        # Clicking an existing marker selects its button instead of dropping a
        # second point on top of it.
        existing = self._marker_at(x, y)
        if existing is not None:
            self.select(existing)
            return

        frac = self._to_fraction(x, y)
        if frac is None:
            return
        self._points[self._selected] = frac
        self.emit("points-changed")
        self.next_unplaced()
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

        for index, (fx, fy) in self._points.items():
            self._draw_marker(
                cr, ox + fx * dw, oy + fy * dh, index,
                style="selected" if index == self._selected else "placed",
            )

        # A faint ghost follows the cursor so you can see where the point you
        # are about to drop will land before committing to it.
        if self._hover is not None and self._selected not in self._points:
            hx, hy = self._hover
            self._draw_marker(cr, ox + hx * dw, oy + hy * dh, self._selected, style="ghost")

    def _draw_marker(self, cr, cx: float, cy: float, index: int, style: str) -> None:
        if style == "selected":
            cr.set_source_rgba(0.10, 0.10, 0.12, 0.95)
            ring = (0.16, 0.78, 0.98, 1.0)
            line_width = 3.0
        elif style == "ghost":
            cr.set_source_rgba(0.13, 0.66, 0.88, 0.35)
            ring = (1.0, 1.0, 1.0, 0.55)
            line_width = 2.0
        else:
            cr.set_source_rgba(0.13, 0.66, 0.88, 0.95)
            ring = (1.0, 1.0, 1.0, 0.95)
            line_width = 2.5

        # new_sub_path() is required: show_text() below leaves a current
        # point, and arc() would otherwise draw a line from it to this circle.
        cr.new_sub_path()
        cr.arc(cx, cy, RADIUS, 0, 6.2832)
        cr.fill_preserve()
        cr.set_source_rgba(*ring)
        cr.set_line_width(line_width)
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
        self._image_path = image_path
        self.set_default_size(1240, 780)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self._title = Adw.WindowTitle(title="Hotspot editor", subtitle=image_path.name)
        header.set_title_widget(self._title)

        save = Gtk.Button(label="Save")
        save.add_css_class("suggested-action")
        save.connect("clicked", self._on_save)
        header.pack_end(save)

        clear = Gtk.Button(icon_name="edit-clear-all-symbolic")
        clear.set_tooltip_text("Remove every hotspot")
        clear.connect("clicked", lambda _b: self._editor.clear())
        header.pack_start(clear)

        toolbar.add_top_bar(header)

        self._editor = HotspotEditor(image_path, points)
        self._editor.connect("selection-changed", lambda *_a: self._sync_rows())
        self._editor.connect("points-changed", lambda *_a: self._sync_rows())

        split = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        split.append(self._build_sidebar())
        split.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        frame = Gtk.Frame()
        frame.set_child(self._editor)
        frame.set_hexpand(True)
        frame.set_vexpand(True)
        split.append(frame)
        toolbar.set_content(split)
        self.set_content(toolbar)

        self._status = Gtk.Label(xalign=0)
        self._status.add_css_class("dim-label")
        self._status.set_margin_start(12)
        self._status.set_margin_end(12)
        toolbar.add_bottom_bar(self._status)

        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key)
        self.add_controller(key)

        self._sync_rows()

    def _build_sidebar(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_size_request(330, -1)

        heading = Gtk.Label(label="Buttons", xalign=0)
        heading.add_css_class("heading")
        box.append(heading)

        hint = Gtk.Label(
            label="Pick a button, then click the picture where it is.",
            xalign=0, wrap=True,
        )
        hint.add_css_class("dim-label")
        hint.add_css_class("caption")
        box.append(hint)

        self._rows: dict[int, Gtk.Widget] = {}
        listbox = Gtk.ListBox()
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        listbox.add_css_class("boxed-list")

        for index, name, g_name in NAMES:
            row = Adw.ActionRow()
            row.set_title(describe(index))
            row.set_subtitle(f"ratbag {index} · manual {manual_number(index)}")
            row.set_activatable(True)
            check = Gtk.Image(icon_name="object-select-symbolic")
            row.add_suffix(check)
            row._check = check
            row.connect("activated", lambda _r, i=index: self._editor.select(i))
            self._rows[index] = row
            listbox.append(row)

        scroller = Gtk.ScrolledWindow()
        scroller.set_child(listbox)
        scroller.set_vexpand(True)
        box.append(scroller)

        return box

    def _sync_rows(self) -> None:
        points = self._editor.points
        selected = self._editor.selected
        for index, row in self._rows.items():
            placed = index in points
            row._check.set_visible(placed)
            row.set_subtitle(
                f"ratbag {index} · manual {manual_number(index)}"
                + ("" if placed else " · not placed")
            )
            if index == selected:
                row.add_css_class("accent")
            else:
                row.remove_css_class("accent")

        placed_count = len(points)
        missing = len(NAMES) - placed_count
        current = describe(selected)
        if missing:
            self._status.set_text(
                f"Placing {current} · {placed_count}/{len(NAMES)} placed, "
                f"{missing} to go · right-click a marker to remove it · Ctrl+S saves"
            )
        else:
            self._status.set_text(
                f"All {len(NAMES)} placed · click a marker to select it · Ctrl+S saves"
            )

    def _on_key(self, _c, keyval, _code, _mods) -> bool:
        if keyval == Gdk.KEY_BackSpace:
            points = self._editor.points
            if self._editor.selected in points:
                del points[self._editor.selected]
                self._editor.queue_draw()
                self._sync_rows()
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
                {"index": index, "x": round(x, 4), "y": round(y, 4)}
                for index, (x, y) in sorted(points.items())
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


def load_points(path: Path) -> dict[int, tuple[float, float]]:
    """Read the saved hotspots, keyed by ratbag index."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    points = {}
    for entry in data.get("hotspots", []):
        try:
            points[int(entry["index"])] = (float(entry["x"]), float(entry["y"]))
        except (KeyError, TypeError, ValueError):
            continue
    return points


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
