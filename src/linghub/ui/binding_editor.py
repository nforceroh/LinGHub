"""The dialog for assigning what a single button does.

Offers the binding types the hardware can actually encode: a key, a modifier
chord, a special action, another mouse button, or nothing. Every choice comes
from binding_labels, which is tested against the encoder, so a choice here
cannot fail later at commit time.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk

from .assignment_catalogue import (
    CHORD,
    DROPDOWN,
    LABELS as MODE_LABELS,
    MODES,
    MODE_CHORD,
    MODE_KEY_MACRO,
    STATIC,
    mode_for,
    single_key_of,
    stored_binding,
)
from .assignment_catalogue import COMMON_KEYS as _CHORD_KEY_CHOICES
from .assignment_catalogue import describe_chord
from .binding_labels import describe_binding
from .buttonmap import describe


class BindingEditor(Adw.Window):
    """Pick a new binding for one button of one profile.

    Calls `on_apply(kind, value)` when the user confirms; the caller decides
    how to persist it, so this widget has no idea the daemon exists.
    """

    def __init__(self, parent, button_index: int, kind: str, value: object, on_apply):
        super().__init__()
        self._index = button_index
        self._on_apply = on_apply
        self._applying = False

        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_default_size(420, -1)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for edge in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{edge}")(18)

        heading = Gtk.Label(xalign=0)
        heading.set_markup(f"<b>{describe(button_index)}</b>")
        box.append(heading)

        subtitle = Gtk.Label(
            label=f"Currently: {describe_binding(kind, value)}", xalign=0
        )
        subtitle.add_css_class("dim-label")
        subtitle.add_css_class("caption")
        box.append(subtitle)

        self._modes = Gtk.DropDown.new_from_strings([label for _mode, label in MODE_LABELS])
        self._modes.connect("notify::selected", lambda *_a: self._sync_mode())
        box.append(self._modes)

        # One stacked page per mode; only the selected one is shown. The pages
        # come from the mode table, so adding a mode is one row there.
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self._stack.set_margin_top(6)
        box.append(self._stack)

        self._dropdowns: dict[str, Gtk.DropDown] = {}
        for mode in MODES:
            if mode.page == DROPDOWN:
                self._dropdowns[mode.name] = self._build_choice_page(mode)
            elif mode.page == CHORD:
                self._build_chord_page(mode.name)
            elif mode.page == STATIC:
                self._build_nothing_page(mode.name)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        actions.set_halign(Gtk.Align.END)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda _b: self.close())
        apply = Gtk.Button(label="Apply")
        apply.add_css_class("suggested-action")
        apply.connect("clicked", self._on_apply_clicked)
        actions.append(cancel)
        actions.append(apply)
        box.append(actions)

        self._error = Gtk.Label(xalign=0)
        self._error.add_css_class("error")
        self._error.set_visible(False)
        box.append(self._error)

        toolbar.set_content(box)
        self.set_content(toolbar)
        self._select_initial_mode(kind, value)
        self._load_initial_value(kind, value)
        self._sync_mode()

    # --- construction ----------------------------------------------------

    def _build_choice_page(self, mode) -> Gtk.DropDown:
        choices = mode.dropdown_choices()
        dropdown = Gtk.DropDown.new_from_strings([label for _value, label in choices])
        dropdown._choices = [value for value, _label in choices]
        wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        wrapper.append(dropdown)
        self._stack.add_named(wrapper, mode.name)
        return dropdown

    def _build_chord_page(self, name: str) -> None:
        wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        self._modifier_checks: dict[str, Gtk.CheckButton] = {}
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        for name_, label in (
            ("KEY_LEFTCTRL", "Ctrl"),
            ("KEY_LEFTSHIFT", "Shift"),
            ("KEY_LEFTALT", "Alt"),
        ):
            check = Gtk.CheckButton(label=label)
            self._modifier_checks[name_] = check
            row.append(check)
        wrapper.append(row)

        self._chord_labels = [label for _name, label in _CHORD_KEY_CHOICES]
        self._chord_key = Gtk.DropDown.new_from_strings(self._chord_labels)
        self._chord_key._choices = [name_ for name_, _label in _CHORD_KEY_CHOICES]
        wrapper.append(self._chord_key)

        self._stack.add_named(wrapper, name)

    def _build_nothing_page(self, name: str) -> None:
        label = Gtk.Label(
            xalign=0,
            wrap=True,
            label=(
                "The button will do nothing. LinGHub records this as a "
                "harmless mouse function rather than an empty mapping, "
                "because an empty mapping corrupts some G502 buttons."
            ),
        )
        label.add_css_class("dim-label")
        self._stack.add_named(label, name)

    def _select_initial_mode(self, kind: str, value: object = None) -> None:
        wanted = mode_for(kind, value)
        for position, (mode, _label) in enumerate(MODE_LABELS):
            if mode == wanted:
                self._modes.set_selected(position)
                break

    def _load_initial_value(self, kind: str, value: object) -> None:
        """Pre-select the binding's current value, so Apply is a no-op first.

        Without this, opening the dialog on an existing binding and pressing
        Apply would silently replace it with whatever was listed first.
        """
        if value is None:
            return
        mode = mode_for(kind, value)
        if mode == MODE_CHORD:
            # The chord page is a set of checkboxes plus a key, not a dropdown.
            self.load_chord(str(value))
            return
        dropdown = self._dropdowns.get(mode)
        if dropdown is None:
            return
        text = single_key_of(str(value)) if mode == MODE_KEY_MACRO else str(value)
        self._select_in(dropdown, text)

    @staticmethod
    def _select_in(dropdown: Gtk.DropDown, value: str) -> None:
        choices = dropdown._choices
        if value in choices:
            dropdown.set_selected(choices.index(value))

    def load_chord(self, spec: str) -> None:
        """Fill the chord page from a saved macro spec.

        Without this the dialog would open an existing chord showing whichever
        key happened to be first in the list, so pressing Apply would silently
        replace the user's chord.
        """
        modifiers: list[str] = []
        key: str | None = None
        for token in str(spec).split():
            if token.startswith("t") and token[1:].isdigit():
                continue
            name = token.lstrip("+-")
            if not name.startswith("KEY_"):
                continue
            if token.startswith("-"):
                continue
            if name in self._modifier_checks:
                modifiers.append(name)
            elif key is None:
                key = name

        for name, check in self._modifier_checks.items():
            check.set_active(name in modifiers)
        if key is not None:
            choices = self._chord_key._choices
            if key in choices:
                self._chord_key.set_selected(choices.index(key))
            else:
                # Not in the common list: add it so the value is not lost.
                choices.append(key)
                self._chord_key.set_model(
                    Gtk.StringList.new([*self._chord_labels, key])
                )
                self._chord_labels.append(key)
                self._chord_key.set_selected(len(choices) - 1)

    # --- state -----------------------------------------------------------

    @property
    def mode(self) -> str:
        return MODE_LABELS[self._modes.get_selected()][0]

    def _sync_mode(self) -> None:
        self._stack.set_visible_child_name(self.mode)

    def _selected_value(self) -> str:
        """The value for the current mode, as the config should store it."""
        mode = self.mode
        dropdown = self._dropdowns.get(mode)
        if dropdown is not None:
            return dropdown._choices[dropdown.get_selected()]
        if mode == MODE_CHORD:
            modifiers = [
                name for name, check in self._modifier_checks.items() if check.get_active()
            ]
            key = self._chord_key._choices[self._chord_key.get_selected()]
            return describe_chord(modifiers + [key])
        return ""

    def _current_binding(self) -> tuple[str, object]:
        return stored_binding(self.mode, self._selected_value())

    def _on_apply_clicked(self, _button) -> None:
        if self._applying:
            return
        self._applying = True
        kind, value = self._current_binding()
        result = self._on_apply(self._index, kind, value)
        self._applying = False

        if isinstance(result, str) and result:
            self.show_error(result)
            return
        if result is False:
            self.show_error("The daemon rejected that binding.")
            return
        self.close()

    def show_error(self, message: str) -> None:
        self._error.set_text(message)
        self._error.set_visible(True)
