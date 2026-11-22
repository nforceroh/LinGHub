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

from . import rules as panel_rules
from .dpi_track import (
    MAX_DPI,
    MIN_DPI,
    DpiTrack,
    preset_color,
    superscript_number,
)
from ..staged_edit import StagedEdit


class DpiPanel(Gtk.Box):
    """Editable DPI slots plus the report rate for one profile."""

    def __init__(self, on_save):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._rates: tuple[int, ...] = ()
        self._staged = StagedEdit(
            self._values,
            on_save=lambda values: on_save(*values),
            on_restore=self._restore,
            on_changed=self._on_changed,
        )

        hint = Gtk.Label(xalign=0, wrap=True)
        hint.add_css_class("dim-label")
        hint.add_css_class("caption")
        hint.set_text(
            "Drag a marker to move a DPI preset. Click one to type an exact value, "
            "or to make it the default or disable it."
        )
        self.append(hint)

        self._legend = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
        )
        self._legend.set_halign(Gtk.Align.CENTER)
        self._legend_labels: list[Gtk.Label] = []
        for index in range(5):
            label = Gtk.Label(xalign=0.5)
            label.add_css_class("caption")
            label.set_visible(False)
            self._legend.append(label)
            self._legend_labels.append(label)
        self.append(self._legend)

        self._track = DpiTrack()
        self._track.set_on_edited(self._on_edited)
        self.append(self._track)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        label = Gtk.Label(label="Report rate", xalign=0)
        label.set_hexpand(True)
        self._rate = Gtk.DropDown.new_from_strings([])
        self._rate.connect("notify::selected", lambda *_a: self._on_edited())
        row.append(label)
        row.append(self._rate)
        self.append(row)

        self._status = Gtk.Label(xalign=0, wrap=True)
        self._status.add_css_class("dim-label")
        self._status.add_css_class("caption")
        self.append(self._status)

        self._staged.mark_saved()

    # --- construction ----------------------------------------------------

    # --- state -----------------------------------------------------------

    def load(self, resolutions: list[dict], rates: tuple[int, ...], report_rate: int) -> None:
        """Fill the panel from a profile's DPI slots and rates."""
        with self._staged.restoring():
            slots = [
                {
                    "dpi": int(slot.get("dpi", MIN_DPI)),
                    "default": bool(slot.get("default")),
                    "disabled": bool(slot.get("disabled")),
                }
                for slot in resolutions
            ]
            self._track.set_slots(slots)
            self._update_legend(slots)

            self._rates = rates or ()
            labels = [f"{rate} Hz" for rate in self._rates]
            self._rate.set_model(Gtk.StringList.new(labels))
            if report_rate in self._rates:
                self._rate.set_selected(self._rates.index(report_rate))
        self._staged.mark_saved()

    def _values(self) -> list:
        slots = [
            (slot["dpi"], slot["default"], slot["disabled"])
            for slot in self._track.slots()
        ]
        rate = self._rates[self._rate.get_selected()] if self._rates else 0
        return [slots, rate]

    @property
    def dirty(self) -> bool:
        return self._staged.dirty

    def _on_edited(self, *_args) -> None:
        self._update_legend(self._track.slots())
        self._staged.edited()

    def _update_legend(self, slots: list[dict]) -> None:
        """Keep the non-control legend in sync with the track presets."""
        for index, label in enumerate(self._legend_labels):
            if index >= len(slots):
                label.set_visible(False)
                continue
            slot = slots[index]
            dpi = int(slot.get("dpi", MIN_DPI))
            disabled = bool(slot.get("disabled"))
            is_default = bool(slot.get("default"))
            red, green, blue = preset_color(index)
            color = (
                f"#{round(red * 255):02x}"
                f"{round(green * 255):02x}"
                f"{round(blue * 255):02x}"
            )
            alpha = "55%" if disabled else "100%"
            underline = ' underline="single"' if is_default else ""
            label.set_markup(
                f'<span foreground="{color}" alpha="{alpha}"{underline}>'
                f"{superscript_number(index + 1)}{dpi}</span>"
            )
            label.set_visible(True)

    def _on_changed(self, changed: bool) -> None:
        self._status.set_text(
            "Unsaved changes — the mouse is unchanged." if changed else ""
        )

    def _save(self) -> None:
        self._staged.save()

    def mark_saved(self) -> None:
        self._staged.mark_saved()

    def revert(self) -> None:
        self._staged.revert()

    def _restore(self, values) -> None:
        """Put the baseline back into the widgets. Called inside restoring()."""
        slots, rate = values
        restored = [
            {"dpi": dpi, "default": is_default, "disabled": disabled}
            for dpi, is_default, disabled in slots
        ]
        self._track.set_slots(restored)
        self._update_legend(restored)
        if rate in self._rates:
            self._rate.set_selected(self._rates.index(rate))
