"""The home screen: one device card on an otherwise empty canvas.

The card is what the window opens on. It answers "what is plugged in, and what
is it doing" — the device name, its charge, and two buttons into the two things
that are not per-profile: LIGHTSYNC and the mouse's onboard memory.

Clicking the mouse itself opens the configuration screen. The card carries no
hotspots: the diagram here is a product image, and selecting a button to edit
belongs on the Assignments view, where there is room to say what each button
does.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import GObject, Gtk

from .buttonmap import DIAGRAM_IMAGE


class DeviceCard(Gtk.Box):
    """A card naming the mouse, its charge, and two ways into it.

    Emits `configure` when the mouse is clicked, and `lightsync` or
    `onboard` for the two buttons.
    """

    __gsignals__ = {
        "configure": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "lightsync": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "onboard": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, image_path: str = DIAGRAM_IMAGE):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        # A card, not a bare box: without a surface the window shows the desktop
        # through it and the card reads as unfinished.
        self.add_css_class("card")
        self.set_margin_top(24)
        self.set_margin_bottom(24)
        self.set_margin_start(24)
        self.set_margin_end(24)

        self._name = Gtk.Label(label="No mouse")
        self._name.add_css_class("title-1")
        self.append(self._name)

        # A Picture, not an Image: an Image draws at its natural size and
        # ignores the space it is given, so the mouse sat small in the middle of
        # a wide window. A Picture scales to fill, keeps the aspect, and can be
        # capped so it does not grow without limit on a large screen.
        self._image = Gtk.Picture.new_for_filename(image_path)
        self._image.set_can_shrink(True)
        self._image.set_content_fit(Gtk.ContentFit.CONTAIN)
        self._image.set_size_request(760, 430)
        self._image.set_can_target(True)
        self._image.set_cursor_from_name("pointer")
        click = Gtk.GestureClick()
        click.connect("released", lambda _g, _n, _x, _y: self.emit("configure"))
        self._image.add_controller(click)
        self.append(self._image)

        # Hidden entirely for a wired mouse: a battery line that says nothing
        # reads as a fault rather than as an absence.
        self._battery = Gtk.Label(label="")
        self._battery.add_css_class("dim-label")
        self._battery.set_visible(False)
        self.append(self._battery)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_halign(Gtk.Align.CENTER)

        lightsync = Gtk.Button(icon_name="weather-clear-symbolic")
        lightsync.set_tooltip_text("LIGHTSYNC")
        lightsync.add_css_class("pill")
        lightsync.connect("clicked", lambda _b: self.emit("lightsync"))
        row.append(lightsync)

        onboard = Gtk.Button(icon_name="drive-harddisk-symbolic")
        onboard.set_tooltip_text("Onboard memory")
        onboard.add_css_class("pill")
        onboard.connect("clicked", lambda _b: self.emit("onboard"))
        row.append(onboard)

        self.append(row)

    def show_device(self, name: str, battery) -> None:
        """Fill the card. `battery` is a Battery, or None for a wired mouse."""
        self._name.set_text(name or "No mouse")
        if battery is None:
            self._battery.set_visible(False)
            return
        suffix = " · charging" if battery.charging else ""
        self._battery.set_text(f"{battery.label}{suffix}")
        self._battery.set_visible(True)