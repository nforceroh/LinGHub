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


# The four modes every supported G502 reports, in libratbag's order.
MODES: tuple[tuple[str, str], ...] = (
    ("off", "Off"),
    ("on", "Fixed colour"),
    ("cycle", "Cycle colours"),
    ("breathing", "Breathing"),
)

# Effects that loop have a speed; a fixed colour does not.
ANIMATED_MODES = ("cycle", "breathing")

DEFAULT_COLOR = (255, 59, 16)
DEFAULT_BRIGHTNESS = 255
DEFAULT_DURATION = 8000


class LedPanel(Gtk.Box):
    """Colour, effect, brightness and speed for one profile's lighting."""

    def __init__(self, on_save, on_revert=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self._on_save = on_save
        self._on_revert = on_revert
        self._loading = False
        self._baseline: tuple | None = None
        self._clean_hint = ""

        self._color_button = Gtk.ColorButton()
        self._color_button.set_title("LED colour")
        self._color_button.connect("notify::rgba", self._on_edited)
        self.append(self._labelled("Colour", self._color_button))

        self._mode = Gtk.DropDown.new_from_strings([label for _m, label in MODES])
        self._mode.connect("notify::selected", self._on_mode_changed)
        self.append(self._labelled("Effect", self._mode))

        self._brightness = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 255, 1
        )
        self._brightness.set_draw_value(True)
        self._brightness.set_value_pos(Gtk.PositionType.RIGHT)
        self._brightness.connect("value-changed", self._on_edited)
        self.append(self._labelled("Brightness", self._brightness))

        # Speed is expressed as a duration, but "fast/slow" is what a user
        # actually thinks in, so the slider is inverted: left is fastest.
        self._speed = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 20, 1)
        self._speed.set_draw_value(False)
        self._speed.connect("value-changed", self._on_edited)
        self._speed_row = self._labelled("Speed", self._speed)
        self.append(self._speed_row)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._revert_button = Gtk.Button(label="Revert")
        self._revert_button.connect("clicked", lambda _b: self.revert())
        self._save_button = Gtk.Button(label="Save lighting")
        self._save_button.add_css_class("suggested-action")
        self._save_button.connect("clicked", lambda _b: self._save())
        actions.append(self._revert_button)
        actions.append(self._save_button)
        self.append(actions)

        self._hint = Gtk.Label(xalign=0, wrap=True)
        self._hint.add_css_class("dim-label")
        self._hint.add_css_class("caption")
        self.append(self._hint)

        self._color_button.set_rgba(self._rgba(DEFAULT_COLOR))
        self._mode.set_selected(1)
        self._brightness.set_value(DEFAULT_BRIGHTNESS)
        self._speed.set_value(self._duration_to_speed(DEFAULT_DURATION))
        self._sync_sensitivity()
        self._update_actions()
        self._baseline = self._values()

    # --- construction ----------------------------------------------------

    def _labelled(self, text: str, widget: Gtk.Widget) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        label = Gtk.Label(label=text, xalign=0)
        label.add_css_class("caption")
        label.add_css_class("dim-label")
        row.append(label)
        row.append(widget)
        return row

    @staticmethod
    def _rgba(color: tuple[int, int, int]):
        from gi.repository import Gdk

        return Gdk.RGBA(*(c / 255 for c in color), 1.0)

    @staticmethod
    def _duration_to_speed(duration: int) -> float:
        """Map a duration in ms onto the 1-20 speed slider (lower is faster)."""
        if duration <= 0:
            return 10
        return max(1, min(20, 20000 / duration))

    @staticmethod
    def _speed_to_duration(speed: float) -> int:
        return int(20000 / max(1, speed))

    # --- state -----------------------------------------------------------

    def load(self, leds: dict[int, dict]) -> None:
        """Fill the panel from a profile's LED zones.

        The zones are shown as one control, so the first zone's values stand
        for all of them. If they ever disagree in the config, the panel shows
        the first and writing will make them agree.
        """
        self._loading = True
        try:
            if not leds:
                self._clean_hint = "This profile has no lighting recorded."
                self._hint.set_text(self._clean_hint)
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
        finally:
            self._loading = False
        self._sync_sensitivity()
        self._baseline = self._values()
        self._update_actions()

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
        animated = self.mode in ANIMATED_MODES
        self._speed_row.set_sensitive(animated)
        self._color_button.set_sensitive(self.mode != "off")
        self._brightness.set_sensitive(self.mode != "off")

    def _values(self) -> tuple:
        """Everything the panel edits, as one comparable tuple."""
        return (self.mode, self.brightness, self.duration, self.color)

    @property
    def dirty(self) -> bool:
        """True when the panel differs from what was last loaded or saved."""
        return self._baseline is not None and self._values() != self._baseline

    def _on_mode_changed(self, *_args) -> None:
        self._sync_sensitivity()
        self._on_edited()

    def _on_edited(self, *_args) -> None:
        """A control changed: record it, but do not touch the mouse."""
        if self._loading:
            return
        self._update_actions()

    def _update_actions(self) -> None:
        changed = self.dirty
        self._save_button.set_sensitive(changed)
        self._revert_button.set_sensitive(changed)
        if changed:
            self._hint.set_text("Unsaved changes — the mouse is unchanged.")
        else:
            self._hint.set_text(self._clean_hint)

    def _save(self) -> None:
        if not self.dirty:
            return
        self._on_save(*self._values())

    def mark_saved(self) -> None:
        """Accept the current values as the saved state."""
        self._baseline = self._values()
        self._update_actions()

    def revert(self) -> None:
        """Throw away unsaved edits and go back to the saved values."""
        if self._baseline is None:
            return
        mode, brightness, duration, color = self._baseline
        self._loading = True
        try:
            for position, (name, _label) in enumerate(MODES):
                if name == mode:
                    self._mode.set_selected(position)
                    break
            self._brightness.set_value(brightness)
            self._speed.set_value(self._duration_to_speed(duration))
            self._color_button.set_rgba(self._rgba(color))
        finally:
            self._loading = False
        self._sync_sensitivity()
        if self._on_revert is not None:
            self._on_revert()
        self._update_actions()
