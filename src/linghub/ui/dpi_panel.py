"""The DPI and report-rate panel for one profile.

Like the lighting panel, edits are staged: nothing reaches the mouse until
Save. A DPI value is a number the user types or steps, so writing per keystroke
would be as wrong as writing per slider pixel.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk

from . import panel_rules


# The range ratbagd accepts for a G502; read from the device where possible.
MIN_DPI = 100
MAX_DPI = 25600


class DpiPanel(Gtk.Box):
    """Editable DPI slots plus the report rate for one profile."""

    def __init__(self, on_save):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self._on_save = on_save
        self._loading = False
        self._baseline: list | None = None
        self._rows: list[dict] = []
        self._rates: tuple[int, ...] = ()

        hint = Gtk.Label(xalign=0, wrap=True)
        hint.add_css_class("dim-label")
        hint.add_css_class("caption")
        hint.set_text(
            "Only the default setting is used until you change DPI in-game. "
            "Disabled slots stay hidden from the mouse's own DPI cycle."
        )
        self.append(hint)

        self._slots_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.append(self._slots_box)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        label = Gtk.Label(label="Report rate", xalign=0)
        label.set_hexpand(True)
        self._rate = Gtk.DropDown.new_from_strings([])
        self._rate.connect("notify::selected", lambda *_a: self._on_edited())
        row.append(label)
        row.append(self._rate)
        self.append(row)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._revert_button = Gtk.Button(label="Revert")
        self._revert_button.connect("clicked", lambda _b: self.revert())
        self._save_button = Gtk.Button(label="Save DPI")
        self._save_button.add_css_class("suggested-action")
        self._save_button.connect("clicked", lambda _b: self._save())
        actions.append(self._revert_button)
        actions.append(self._save_button)
        self.append(actions)

        self._status = Gtk.Label(xalign=0, wrap=True)
        self._status.add_css_class("dim-label")
        self._status.add_css_class("caption")
        self.append(self._status)

        self._update_actions()

    # --- construction ----------------------------------------------------

    def _build_slot_row(self, index: int) -> dict:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        name = Gtk.Label(label=f"Slot {index + 1}", xalign=0)
        name.set_size_request(64, -1)
        row.append(name)

        spin = Gtk.SpinButton.new_with_range(MIN_DPI, MAX_DPI, 50)
        spin.set_hexpand(True)
        spin.connect("value-changed", lambda *_a: self._on_edited())
        row.append(spin)

        unit = Gtk.Label(label="dpi", xalign=0)
        unit.add_css_class("dim-label")
        row.append(unit)

        default = Gtk.CheckButton(label="Default")
        default.set_tooltip_text("The setting the mouse uses by default")
        default.connect("toggled", lambda *_a: self._on_toggled(index))
        row.append(default)

        disabled = Gtk.CheckButton(label="Disabled")
        disabled.set_tooltip_text("Hidden from the mouse's DPI cycle")
        disabled.connect("toggled", lambda *_a: self._on_edited())
        row.append(disabled)

        self._slots_box.append(row)
        return {"spin": spin, "default": default, "disabled": disabled}

    def _on_toggled(self, index: int) -> None:
        """Only one slot may be the default, so ticking one clears the rest."""
        if self._loading:
            return
        current = [row["default"].get_active() for row in self._rows]
        wanted = panel_rules.default_mask(
            current, index, on=self._rows[index]["default"].get_active()
        )
        self._loading = True
        try:
            for row, active in zip(self._rows, wanted):
                row["default"].set_active(active)
        finally:
            self._loading = False
        self._on_edited()

    # --- state -----------------------------------------------------------

    def load(self, resolutions: list[dict], rates: tuple[int, ...], report_rate: int) -> None:
        """Fill the panel from a profile's DPI slots and rates."""
        self._loading = True
        try:
            while len(self._rows) < len(resolutions):
                self._rows.append(self._build_slot_row(len(self._rows)))
            for position, slot in enumerate(resolutions):
                row = self._rows[position]
                row["spin"].set_value(slot.get("dpi", MIN_DPI))
                row["default"].set_active(bool(slot.get("default")))
                row["disabled"].set_active(bool(slot.get("disabled")))

            self._rates = rates or ()
            labels = [f"{rate} Hz" for rate in self._rates]
            self._rate.set_model(Gtk.StringList.new(labels))
            if report_rate in self._rates:
                self._rate.set_selected(self._rates.index(report_rate))
        finally:
            self._loading = False
        self._baseline = self._values()
        self._update_actions()

    def _values(self) -> list:
        slots = [
            (
                int(row["spin"].get_value()),
                bool(row["default"].get_active()),
                bool(row["disabled"].get_active()),
            )
            for row in self._rows
        ]
        rate = self._rates[self._rate.get_selected()] if self._rates else 0
        return [slots, rate]

    @property
    def dirty(self) -> bool:
        return self._baseline is not None and self._values() != self._baseline

    def _on_edited(self, *_args) -> None:
        if self._loading:
            return
        self._update_actions()

    def _update_actions(self) -> None:
        changed = self.dirty
        self._save_button.set_sensitive(changed)
        self._revert_button.set_sensitive(changed)
        self._status.set_text(
            "Unsaved changes — the mouse is unchanged." if changed else ""
        )

    def _save(self) -> None:
        if not self.dirty:
            return
        slots, rate = self._values()
        self._on_save(slots, rate)

    def mark_saved(self) -> None:
        self._baseline = self._values()
        self._update_actions()

    def revert(self) -> None:
        if self._baseline is None:
            return
        slots, rate = self._baseline
        self._loading = True
        try:
            for row, (dpi, is_default, disabled) in zip(self._rows, slots):
                row["spin"].set_value(dpi)
                row["default"].set_active(is_default)
                row["disabled"].set_active(disabled)
            if rate in self._rates:
                self._rate.set_selected(self._rates.index(rate))
        finally:
            self._loading = False
        self._update_actions()
