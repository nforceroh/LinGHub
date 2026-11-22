"""The lighting panel: one colour, one effect, for the whole profile.

The G502 has two LED zones, but they read as one strip to a user, so the panel
drives them together. The hardware still stores them separately; the daemon
writes the same values to each.

Editing is staged rather than live: nothing reaches the mouse until Save is
pressed. Sliders fire `value-changed` on every pixel, so writing as you drag
meant one config write and two hardware commits per pixel.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk

from .rules import MODES, controls_for, duration_to_speed, speed_to_duration
from ..staged_edit import StagedEdit

DEFAULT_COLOR = (255, 59, 16)
DEFAULT_BRIGHTNESS = 255
DEFAULT_DURATION = 8000


class EffectControl(Gtk.MenuButton):
    """The effect picker as a popover listing the four hardware effects."""

    def __init__(self):
        super().__init__()
        self._selected = 1  # Fixed colour, the hardware default.
        self.set_always_show_arrow(True)
        self._label = Gtk.Label(label=MODES[self._selected][1], xalign=0)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.append(self._label)
        self.set_child(box)

        popover = Gtk.Popover()
        list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        list_box.set_margin_top(8)
        list_box.set_margin_bottom(8)
        list_box.set_margin_start(8)
        list_box.set_margin_end(8)

        heading = Gtk.Label(label="EFFECTS", xalign=0)
        heading.add_css_class("heading")
        list_box.append(heading)

        for position, (_name, label) in enumerate(MODES):
            row = Gtk.Button(label=label)
            row.add_css_class("flat")
            row.set_halign(Gtk.Align.FILL)
            row.connect("clicked", lambda _b, index=position: self._choose(index))
            list_box.append(row)

        popover.set_child(list_box)
        self.set_popover(popover)

    def _choose(self, position: int) -> None:
        self._selected = position
        self._label.set_text(MODES[position][1])
        self.emit("notify::selected-item")
        self.get_popover().popdown()

    def get_selected(self) -> int:
        return self._selected

    def set_selected(self, position: int) -> None:
        position = max(0, min(len(MODES) - 1, int(position)))
        self._selected = position
        self._label.set_text(MODES[position][1])


class LedPanel(Gtk.Box):
    """Colour, effect, brightness and speed for one profile's lighting."""

    def __init__(self, on_save, on_revert=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._on_revert = on_revert
        self._clean_hint = ""
        self._staged = StagedEdit(
            self._values,
            on_save=lambda values: on_save(*values),
            on_restore=self._restore,
            on_changed=self._on_changed,
        )

        # A compact settings panel mirrors the reference: one choice per row,
        # with the live value shown beside each slider. The panel keeps a
        # natural width rather than stretching, so the rows read as a form
        # instead of spanning the whole window.
        self.set_valign(Gtk.Align.START)
        self.set_size_request(320, -1)
        self.set_margin_top(6)
        self.set_margin_bottom(6)
        self.set_margin_start(6)
        self.set_margin_end(6)

        self._color_button = Gtk.ColorButton()
        self._color_button.set_title("LED colour")
        self._color_button.connect("notify::rgba", self._on_edited)

        effect = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        effect.append(self._field_label("Effect"))
        self._mode = EffectControl()
        self._mode.connect("notify::selected", self._on_mode_changed)
        self._mode.set_hexpand(True)
        self._mode.set_halign(Gtk.Align.FILL)
        effect.append(self._mode)
        self.append(effect)

        colour = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        colour.append(self._field_label("Colour"))
        self._color_button.set_halign(Gtk.Align.START)
        colour.append(self._color_button)
        self.append(colour)

        self._brightness = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 255, 1
        )
        self._brightness.set_draw_value(False)
        self._brightness.set_hexpand(True)
        self._brightness.connect("value-changed", self._on_edited)
        self._brightness_value = Gtk.Label(label="255", xalign=1)
        self._brightness_value.add_css_class("heading")
        brightness = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        brightness.append(self._field_label("Brightness"))
        brightness_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
        )
        brightness_row.append(self._brightness)
        brightness_row.append(self._brightness_value)
        brightness.append(brightness_row)
        self.append(brightness)
        self._brightness.connect(
            "value-changed",
            lambda *_args: self._brightness_value.set_text(
                str(round(self._brightness.get_value()))
            ),
        )

        # Speed is expressed as a duration, but "fast/slow" is what a user
        # actually thinks in, so the slider is inverted: left is fastest.
        self._speed = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 20, 1)
        self._speed.set_draw_value(False)
        self._speed.set_hexpand(True)
        self._speed.connect("value-changed", self._on_edited)
        self._speed_value = Gtk.Label(label="8000ms", xalign=1)
        self._speed_value.add_css_class("heading")
        speed = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        speed.append(self._field_label("Rate"))
        speed_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        speed_row.append(self._speed)
        speed_row.append(self._speed_value)
        speed.append(speed_row)
        self._speed_row = speed
        self.append(speed)
        self._speed.connect(
            "value-changed",
            lambda *_args: self._speed_value.set_text(
                f"{self._speed_to_duration(self._speed.get_value())}ms"
            ),
        )

        self._hint = Gtk.Label(xalign=0, wrap=True)
        self._hint.add_css_class("dim-label")
        self._hint.add_css_class("caption")
        self.append(self._hint)

        self._color_button.set_rgba(self._rgba(DEFAULT_COLOR))
        self._mode.set_selected(1)
        self._brightness.set_value(DEFAULT_BRIGHTNESS)
        self._speed.set_value(self._duration_to_speed(DEFAULT_DURATION))
        self._sync_sensitivity()
        self._staged.mark_saved()

    # --- construction ----------------------------------------------------

    def _labelled(self, text: str, widget: Gtk.Widget) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        label = self._field_label(text)
        row.append(label)
        row.append(widget)
        return row

    def _field_label(self, text: str) -> Gtk.Label:
        label = Gtk.Label(label=text, xalign=0)
        label.add_css_class("heading")
        return label

    @staticmethod
    def _rgba(color: tuple[int, int, int]):
        from gi.repository import Gdk

        return Gdk.RGBA(*(c / 255 for c in color), 1.0)

    # The conversions are kept here as names so existing callers and tests do
    # not have to change; the arithmetic itself lives in panel_rules.
    _duration_to_speed = staticmethod(duration_to_speed)
    _speed_to_duration = staticmethod(speed_to_duration)

    # --- state -----------------------------------------------------------

    def load(self, leds: dict[int, dict]) -> None:
        """Fill the panel from a profile's LED zones.

        The zones are shown as one control, so the first zone's values stand
        for all of them. If they ever disagree in the config, the panel shows
        the first and writing will make them agree.
        """
        with self._staged.restoring():
            if not leds:
                self._clean_hint = "This profile has no lighting recorded."
                self._hint.set_text(self._clean_hint)
                self._sync_sensitivity()
                return
            first = leds[min(leds)]
            mode = first.get("mode", "on")
            for position, (name, _label) in enumerate(MODES):
                if name == mode:
                    self._mode.set_selected(position)
                    break
            self._color_button.set_rgba(self._rgba(first.get("color") or DEFAULT_COLOR))
            self._brightness.set_value(first.get("brightness", DEFAULT_BRIGHTNESS))
            self._speed.set_value(
                self._duration_to_speed(first.get("duration", DEFAULT_DURATION))
            )
            self._clean_hint = f"{len(leds)} LED zone(s) set together."
            self._hint.set_text(self._clean_hint)
        self._sync_sensitivity()
        self._staged.mark_saved()

    @property
    def mode(self) -> str:
        return MODES[self._mode.get_selected()][0]

    @property
    def color(self) -> tuple[int, int, int]:
        rgba = self._color_button.get_rgba()
        return (
            round(rgba.red * 255),
            round(rgba.green * 255),
            round(rgba.blue * 255),
        )

    @property
    def brightness(self) -> int:
        return round(self._brightness.get_value())

    @property
    def duration(self) -> int:
        return self._speed_to_duration(self._speed.get_value())

    def _sync_sensitivity(self) -> None:
        """Only the looping effects have a speed, and colour is moot when off."""
        controls = controls_for(self.mode)
        self._speed_row.set_sensitive(controls.speed)
        self._color_button.set_sensitive(controls.color)
        self._brightness.set_sensitive(controls.brightness)

    def _values(self) -> tuple:
        """Everything the panel edits, as one comparable tuple."""
        return (self.mode, self.brightness, self.duration, self.color)

    @property
    def dirty(self) -> bool:
        """True when the panel differs from what was last loaded or saved."""
        return self._staged.dirty

    def _on_mode_changed(self, *_args) -> None:
        self._sync_sensitivity()
        self._staged.edited()

    def _on_edited(self, *_args) -> None:
        """A control changed: record it, but do not touch the mouse."""
        self._staged.edited()

    def _on_changed(self, changed: bool) -> None:
        """The staged edit says whether the panel is dirty; show it."""
        if changed:
            self._hint.set_text("Unsaved changes — the mouse is unchanged.")
        else:
            self._hint.set_text(self._clean_hint)

    def _save(self) -> None:
        self._staged.save()

    def mark_saved(self) -> None:
        """Accept the current values as the saved state."""
        self._staged.mark_saved()

    def revert(self) -> None:
        """Throw away unsaved edits and go back to the saved values."""
        self._staged.revert()

    def _restore(self, values) -> None:
        """Put the baseline back into the widgets. Called inside restoring()."""
        mode, brightness, duration, color = values
        for position, (name, _label) in enumerate(MODES):
            if name == mode:
                self._mode.set_selected(position)
                break
        self._brightness.set_value(brightness)
        self._speed.set_value(self._duration_to_speed(duration))
        self._color_button.set_rgba(self._rgba(color))
        self._sync_sensitivity()
        if self._on_revert is not None:
            self._on_revert()
