"""The home screen: one card on an otherwise empty canvas.

The card is what the window opens on. It answers "what is plugged in, and what
is it doing" — the device name, its charge, and two buttons into the two things
that are not per-profile: LIGHTSYNC and the mouse's onboard memory.

Clicking the mouse itself opens the configuration screen. The card carries no
hotspots: the diagram here is a product image, and selecting a button to edit
belongs on the Assignments view, where there is room to say what each button
does.

The layout follows the reference: a compact card, name and charge top-left, the
mouse centred, the two buttons bottom-right. Everything centred read as a
placeholder rather than a card.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import GObject, Gtk

from .buttonmap import DIAGRAM_IMAGE

# The card is compact, like the reference: wide enough for the name and the
# image, narrow enough that it reads as one object rather than a panel.
CARD_WIDTH = 340

# The mouse's drawn height. The image is 705x400, so this also sets the width:
# 300px tall is 529px wide, which is why the card is wider than the reference's.
IMAGE_HEIGHT = 300


class HomeCard(Gtk.Frame):
    """The home screen's card: the device card, its charge, and two ways into it.

    Emits `configure` when the mouse is clicked, and `lightsync` or
    `onboard` for the two buttons.
    """

    __gsignals__ = {
        "configure": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "lightsync": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "onboard": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, image_path: str = DIAGRAM_IMAGE):
        super().__init__()
        self.set_size_request(CARD_WIDTH, -1)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(16)
        box.set_margin_bottom(12)
        box.set_margin_start(16)
        box.set_margin_end(16)
        self.set_child(box)

        # Name and charge share the top-left, as the reference does. The charge
        # is a caption under the name, not a line of its own, so the two read as
        # one header.
        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        header.set_halign(Gtk.Align.START)
        self._name = Gtk.Label(label="No mouse", xalign=0)
        self._name.add_css_class("heading")
        header.append(self._name)

        self._battery = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._battery.set_halign(Gtk.Align.START)
        self._battery_label = Gtk.Label(label="", xalign=0)
        self._battery_label.add_css_class("caption")
        self._battery_label.add_css_class("dim-label")
        self._battery.append(self._battery_label)
        self._battery_icon = Gtk.Image()
        self._battery.append(self._battery_icon)
        # Hidden entirely for a wired mouse: a battery line that says nothing
        # reads as a fault rather than as an absence.
        self._battery.set_visible(False)
        header.append(self._battery)
        box.append(header)

        # An Image with an explicit pixel size, not a Picture. A Picture's
        # natural size is the image's own, and a size_request is a minimum
        # rather than a cap, so the card grew to 513px with the mouse
        # letterboxed in dead space above and below. set_pixel_size scales to
        # exactly that height with the aspect preserved, which is what the
        # card actually wants.
        self._image = Gtk.Image.new_from_file(image_path)
        self._image.set_pixel_size(IMAGE_HEIGHT)
        self._image.set_can_target(True)
        self._image.set_cursor_from_name("pointer")
        click = Gtk.GestureClick()
        click.connect("released", lambda _g, _n, _x, _y: self.emit("configure"))
        self._image.add_controller(click)
        box.append(self._image)

        # The two buttons sit bottom-right, as the reference does. They are the
        # two things that are not per-profile, so they are card-level actions
        # rather than part of the header.
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_halign(Gtk.Align.END)

        lightsync = Gtk.Button(icon_name="weather-clear-symbolic")
        lightsync.set_tooltip_text("LIGHTSYNC")
        lightsync.add_css_class("flat")
        lightsync.connect("clicked", lambda _b: self.emit("lightsync"))
        row.append(lightsync)

        onboard = Gtk.Button(icon_name="drive-harddisk-symbolic")
        onboard.set_tooltip_text("Onboard memory")
        onboard.add_css_class("flat")
        onboard.connect("clicked", lambda _b: self.emit("onboard"))
        row.append(onboard)

        box.append(row)

    def show_device(self, name: str, battery) -> None:
        """Fill the card. `battery` is a Battery, or None for a wired mouse."""
        self._name.set_text(name or "No mouse")
        if battery is None:
            self._battery.set_visible(False)
            return
        self._battery_label.set_text(f"{battery.capacity}%")
        # A charging battery gets its own icon; the kernel's status is the only
        # source, so a discharging mouse shows the plain battery.
        icon = (
            "battery-full-charging-symbolic"
            if battery.charging
            else "battery-good-symbolic"
        )
        self._battery_icon.set_from_icon_name(icon)
        self._battery.set_visible(True)
