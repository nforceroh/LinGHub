"""The narrow view rail on the configuration screen.

The rail switches between the three configuration views. It intentionally
stays out of the content model: a view is just a name, and the window owns
the stack that puts the selected view on screen.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk


class ConfigRail(Gtk.Box):
    """DPI, Assignments and LIGHTSYNC icons, with Manage below."""

    def __init__(self, on_view, on_manage):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.set_size_request(52, -1)
        self.set_margin_top(8)
        self.set_margin_bottom(8)
        self.set_margin_start(6)
        self.set_margin_end(6)

        self._on_view = on_view
        self._buttons: dict[str, Gtk.ToggleButton] = {}

        self._add_view("dpi", "crosshair-symbolic", "Sensitivity (DPI)")
        self._add_view("assignments", "input-mouse-symbolic", "Assignments")
        self._add_view("lightsync", "weather-clear-symbolic", "LIGHTSYNC")

        manage = Gtk.Button(icon_name="emblem-system-symbolic")
        manage.set_tooltip_text("Manage profiles")
        manage.set_vexpand(True)
        manage.set_valign(Gtk.Align.END)
        manage.add_css_class("flat")
        manage.connect("clicked", lambda _b: on_manage())
        self.append(manage)

        self.select("assignments")

    def _add_view(self, name: str, icon: str, tooltip: str) -> None:
        button = Gtk.ToggleButton()
        button.set_child(Gtk.Image.new_from_icon_name(icon))
        button.set_tooltip_text(tooltip)
        button.add_css_class("flat")
        button.set_halign(Gtk.Align.CENTER)
        button.connect("toggled", lambda b, n=name: self._on_toggled(n, b))
        self.append(button)
        self._buttons[name] = button

    def _on_toggled(self, name: str, button: Gtk.ToggleButton) -> None:
        if not button.get_active():
            return
        for other_name, other in self._buttons.items():
            if other_name != name:
                other.set_active(False)
        self._on_view(name)

    def select(self, name: str) -> None:
        """Set the active view without changing the stack directly."""
        button = self._buttons.get(name)
        if button is not None:
            button.set_active(True)
