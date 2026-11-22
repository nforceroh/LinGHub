"""The searchable assignment sidebar for the Assignments view.

It exposes the binding choices the hardware can actually encode. Choosing a
row stages the assignment for the selected button; the window owns the save
and the daemon write, so this widget does not touch the mouse or config.
"""

from __future__ import annotations

from dataclasses import dataclass

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk

from .binding_labels import (
    BUTTON_CHOICES,
    COMMON_KEYS,
    SPECIAL_CHOICES,
)


@dataclass(frozen=True)
class AssignmentChoice:
    kind: str
    value: object
    label: str
    group: str


def assignment_choices() -> tuple[AssignmentChoice, ...]:
    """Every direct assignment choice, plus Nothing."""
    choices = []
    for value, label in COMMON_KEYS:
        choices.append(AssignmentChoice("key", value, label, "Keys"))
        choices.append(AssignmentChoice("macro", value, f"{label} (macro)", "Keys"))
    for value, label in SPECIAL_CHOICES:
        choices.append(AssignmentChoice("special", value, label, "Mouse actions"))
    for value, label in BUTTON_CHOICES:
        choices.append(AssignmentChoice("button", value, label, "Mouse buttons"))
    choices.append(AssignmentChoice("disabled", None, "Nothing", "Other"))
    return tuple(choices)


def filter_assignment_choices(
    choices: tuple[AssignmentChoice, ...], query: str
) -> tuple[AssignmentChoice, ...]:
    """Case-insensitive label/group search."""
    needle = query.strip().casefold()
    if not needle:
        return choices
    return tuple(
        choice
        for choice in choices
        if needle in choice.label.casefold()
        or needle in choice.group.casefold()
    )


class AssignmentSidebar(Gtk.Box):
    """Searchable assignment choices for the selected mouse button."""

    def __init__(self, on_chosen):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.set_size_request(300, -1)
        self.set_margin_top(12)
        self.set_margin_bottom(12)
        self.set_margin_start(12)
        self.set_margin_end(12)
        self._on_chosen = on_chosen
        self._choices = assignment_choices()
        self._rows: dict[str, Gtk.ListBoxRow] = {}

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        heading = Gtk.Label(label="Assignments", xalign=0)
        heading.add_css_class("heading")
        heading.set_hexpand(True)
        header.append(heading)
        header.append(Gtk.Image.new_from_icon_name("changes-prevent-symbolic"))
        self.append(header)

        self._search = Gtk.SearchEntry()
        self._search.set_placeholder_text("Search assignments")
        self._search.connect("search-changed", lambda *_a: self._refill())
        self.append(self._search)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)

        self._list = Gtk.ListBox()
        self._list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._list.connect("row-activated", self._on_row_activated)
        scroller.set_child(self._list)
        self.append(scroller)

        self._refill()

    def _refill(self) -> None:
        while True:
            child = self._list.get_first_child()
            if child is None:
                break
            self._list.remove(child)
        self._rows.clear()

        for choice in filter_assignment_choices(
            self._choices, self._search.get_text()
        ):
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            box.set_margin_top(6)
            box.set_margin_bottom(6)
            box.set_margin_start(8)
            box.set_margin_end(8)
            title = Gtk.Label(label=choice.label, xalign=0)
            title.set_wrap(True)
            box.append(title)
            group = Gtk.Label(label=choice.group, xalign=0)
            group.add_css_class("caption")
            group.add_css_class("dim-label")
            box.append(group)
            row.set_child(box)
            row._choice = choice
            self._list.append(row)
            key = f"{choice.group}:{choice.kind}:{choice.label}"
            self._rows[key] = row

    def _on_row_activated(self, _list, row: Gtk.ListBoxRow) -> None:
        choice = getattr(row, "_choice", None)
        if choice is None:
            return
        self._on_chosen(choice.kind, choice.value)
