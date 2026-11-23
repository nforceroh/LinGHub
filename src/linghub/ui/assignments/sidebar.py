"""The searchable assignment sidebar for the Assignments view.

It exposes the binding choices the hardware can actually encode. Choosing a
row stages the assignment for the selected button; the window owns the save
and the daemon write, so this widget does not touch the mouse or config.

The choices, their groups and their labels come from the assignment
catalogue, which the binding editor reads too — one vocabulary, two views.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gdk, Gtk, Pango

from .catalogue import (
    GROUPS,
    AssignmentChoice,
    assignment_choices,
    choices_in_group,
    filter_assignment_choices,
)


class AssignmentSidebar(Gtk.Box):
    """Searchable assignment choices for the selected mouse button."""

    def __init__(self, on_chosen):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.set_size_request(340, -1)
        self.set_margin_top(12)
        self.set_margin_bottom(12)
        self.set_margin_start(12)
        self.set_margin_end(12)
        self._on_chosen = on_chosen
        self._choices = assignment_choices()
        # Commands is the active group from the start, so the first fill is
        # already filtered and the rows never show their group captions.
        self._group: str | None = "Commands"

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        heading = Gtk.Label(label="Assignments", xalign=0)
        heading.add_css_class("heading")
        heading.set_hexpand(True)
        header.append(heading)
        self.append(header)

        # One clickable tab per group. Selecting one filters the list to that
        # group's actions; clicking the active tab again shows everything.
        self._tabs = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._tab_buttons: dict[str, Gtk.ToggleButton] = {}
        for group in GROUPS:
            button = Gtk.ToggleButton(label=group)
            button.add_css_class("flat")
            button.set_tooltip_text(f"Show {group.lower()} only")
            button.connect(
                "toggled",
                lambda btn, name=group: self._on_group_toggled(name, btn),
            )
            self._tabs.append(button)
            self._tab_buttons[group] = button
        self.append(self._tabs)

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
        # Selecting the tab after construction, once _list exists: the
        # toggled handler refills, so this also applies the initial filter.
        self._tab_buttons["Commands"].set_active(True)

    def _refill(self) -> None:
        while True:
            child = self._list.get_first_child()
            if child is None:
                break
            self._list.remove(child)

        pool = self._choices
        if self._group is not None:
            pool = choices_in_group(pool, self._group)
        for choice in filter_assignment_choices(
            pool, self._search.get_text()
        ):
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            box.set_margin_top(2)
            box.set_margin_bottom(2)
            box.set_margin_start(8)
            box.set_margin_end(8)
            title = Gtk.Label(label=choice.label, xalign=0)
            title.set_ellipsize(Pango.EllipsizeMode.END)
            box.append(title)
            # The group caption is only useful in the unfiltered view, where
            # rows from different groups sit together; within a group tab it
            # repeats what the tab already says.
            if self._group is None:
                group = Gtk.Label(label=choice.group, xalign=0)
                group.add_css_class("caption")
                group.add_css_class("dim-label")
                box.append(group)
            row.set_child(box)
            row._choice = choice
            drag = Gtk.DragSource()
            drag.set_actions(Gdk.DragAction.COPY)
            drag.connect("prepare", self._on_drag_prepare)
            row.add_controller(drag)
            self._list.append(row)

    def _on_drag_prepare(self, source, _x: float, _y: float):
        """The dragged row's choice as the drag payload.

        GTK needs a GdkContentProvider, not a bare object: returning the
        choice directly made the drag start and immediately die, so a drop
        never happened anywhere. The source is found from the widget the drag
        started on, not from the list selection: dragging a row the user
        never clicked must still carry that row's choice.
        """
        widget = source.get_widget()
        row = widget if isinstance(widget, Gtk.ListBoxRow) else None
        if row is None or not hasattr(row, "_choice"):
            return None
        return Gdk.ContentProvider.new_for_value(row._choice)

    def _on_group_toggled(self, group: str, button: Gtk.ToggleButton) -> None:
        if not button.get_active():
            return
        for name, other in self._tab_buttons.items():
            if name != group:
                other.set_active(False)
        self._group = group
        self._refill()

    def _on_row_activated(self, _list, row: Gtk.ListBoxRow) -> None:
        choice = getattr(row, "_choice", None)
        if choice is None:
            return
        self._on_chosen(choice.kind, choice.value)

