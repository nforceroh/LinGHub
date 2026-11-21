"""The profile selector: a dropdown that chooses and loads a profile.

This replaces the profile list that used to sit in the main pane. Two places to
choose a profile was the ambiguity the DPI panel grilling removed, so the
selector owns which profile the panels show.

Choosing a profile here **loads it onto the mouse**. The old window had two
actions on one list — selecting chose what to edit, `Load` put it on the mouse —
and that distinction is the thing users are least likely to expect. Editing a
profile you have not loaded stays possible through `Manage profiles`.

The search field is hidden below a threshold. The dropdown is the only way to
switch, so a long list would be painful without it, but a field above three
profiles is furniture.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk

# Below this many profiles the search field is hidden.
SEARCH_THRESHOLD = 8


class ProfileSelector(Gtk.MenuButton):
    """A dropdown listing every profile, with a search field and Manage."""

    def __init__(self, on_chosen, on_manage):
        super().__init__()
        self._on_chosen = on_chosen
        self._on_manage = on_manage
        self._rows: dict[str, Gtk.Button] = {}
        self._names: tuple[str, ...] = ()
        self._active: str | None = None
        self._editing: str | None = None

        self.add_css_class("flat")
        self.set_tooltip_text("Choose the profile to edit and load")

        self._label = Gtk.Label(label="No profile")
        self._label.add_css_class("heading")
        self.set_child(self._label)

        # No set_parent: a MenuButton parents the popover it is given, and
        # doing it twice trips a GTK assertion.
        self._popover = Gtk.Popover()
        self.set_popover(self._popover)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(8)
        box.set_margin_end(8)

        self._search = Gtk.SearchEntry()
        self._search.set_placeholder_text("Search profiles…")
        # `changed`, not `search-changed`: the latter is debounced by 150ms,
        # which makes the list feel laggy behind the typing and makes the
        # filter untestable without a main loop.
        self._search.connect("changed", lambda _e: self._apply_filter())
        box.append(self._search)

        # A ListBox rather than a Box: it can insert at a position, and it
        # gives the rows arrow-key navigation for free.
        self._list = Gtk.ListBox()
        self._list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list.add_css_class("navigation-sidebar")
        scroller = Gtk.ScrolledWindow()
        scroller.set_child(self._list)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_max_content_height(320)
        scroller.set_propagate_natural_height(True)
        box.append(scroller)

        box.append(Gtk.Separator())

        manage = Gtk.Button(label="Manage profiles")
        manage.add_css_class("flat")
        manage.connect("clicked", lambda _b: self._manage())
        box.append(manage)

        self._list.connect("row-activated", self._on_row_activated)
        self._popover.set_child(box)

    # --- state -----------------------------------------------------------

    def show_profiles(
        self, names: tuple[str, ...], *, active: str | None, editing: str | None
    ) -> None:
        """Fill the dropdown. `active` is on the mouse; `editing` is shown."""
        self._names = tuple(names)
        self._active = active
        self._editing = editing

        for name in [n for n in self._rows if n not in names]:
            self._list.remove(self._rows.pop(name))

        for position, name in enumerate(names):
            row = self._rows.get(name)
            if row is None:
                row = self._make_row(name)
                self._rows[name] = row
                self._list.insert(row, position)
            self._style_row(row, name)

        self._search.set_visible(len(names) >= SEARCH_THRESHOLD)
        self._label.set_text(editing or "No profile")
        self._apply_filter()

    def _make_row(self, name: str) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.set_activatable(True)
        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        content.set_margin_top(6)
        content.set_margin_bottom(6)
        content.set_margin_start(8)
        content.set_margin_end(8)
        check = Gtk.Image.new_from_icon_name("object-select-symbolic")
        content.append(check)
        label = Gtk.Label(label=name, xalign=0)
        label.set_hexpand(True)
        content.append(label)
        row.set_child(content)
        row._check = check
        row._label = label
        row._name = name
        return row

    def _style_row(self, row: Gtk.ListBoxRow, name: str) -> None:
        """The active profile is blue and ticked; the edited one is bold.

        Colour alone fails for colourblind users, so the tick carries the same
        fact. The two are separate because a profile can be edited without
        being loaded.
        """
        on_the_mouse = name == self._active
        row._check.set_visible(on_the_mouse)
        if on_the_mouse:
            row._label.add_css_class("accent")
        else:
            row._label.remove_css_class("accent")
        if name == self._editing:
            row._label.add_css_class("heading")
        else:
            row._label.remove_css_class("heading")

    def _apply_filter(self) -> None:
        wanted = self._search.get_text().strip().casefold()
        for name, row in self._rows.items():
            row.set_visible(not wanted or wanted in name.casefold())

    def _on_row_activated(self, _list, row) -> None:
        if row is not None:
            self._choose(row._name)

    def _choose(self, name: str) -> None:
        self._popover.popdown()
        self._on_chosen(name)

    def _manage(self) -> None:
        self._popover.popdown()
        self._on_manage()
