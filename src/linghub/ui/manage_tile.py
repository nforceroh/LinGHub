"""The two tiles the manage-profiles canvas is made of.

A game tile shows the display name the user chose (or the stripped
executable, per spec §2.7), and a profile tile shows its name plus the
one-line summary — the default preset's DPI and the report rate. The
reference's blurred screenshot preview is decoration we cannot produce; a
summary is information a user can compare across profiles.

Both are click targets, not buttons: a tile that looks like a button invites
"click to do what?". The profile tile's DETAILS action is the flow into the
main window's panels; the game tile's click re-opens the add-game dialog with
its fields filled in, which is how a display name is renamed.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import GObject, Gtk

from ..daemon_view import ProfileSummary


TILE_WIDTH = 200


def profile_summary_line(summary: ProfileSummary) -> str:
    """The one-line summary a profile tile shows under its name.

    Both facts are optional — a desktop profile has neither a default DPI
    preset nor a report rate — so the line holds only what is known, and a
    tile with neither shows no line at all rather than "0 DPI · 0 Hz".
    """
    parts = []
    if summary.dpi:
        parts.append(f"{summary.dpi} DPI")
    if summary.report_rate:
        parts.append(f"{summary.report_rate} Hz")
    return " · ".join(parts)


class AddTile(Gtk.Button):
    """The `+ ADD …` tile that starts each row.

    A tile, not a plain button, so it sits in the row with the same shape and
    height as the tiles beside it.
    """

    def __init__(self, label: str):
        super().__init__()
        self.set_label(label)
        self.set_size_request(TILE_WIDTH, 120)
        self.set_hexpand(False)

    def clicked(self, on_click) -> None:
        self.connect("clicked", lambda _b: on_click())


class GameTile(Gtk.Button):
    """One game's tile: its display name, in the games row.

    Clicking it re-opens the add-game dialog for this game, which is how the
    display name is renamed later. There is no separate edit affordance: the
    tile is the affordance.
    """

    def __init__(self, executable: str, name: str, on_edit):
        super().__init__()
        self._executable = executable

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_valign(Gtk.Align.CENTER)
        box.append(Gtk.Label(label=name, wrap=True))
        self.set_child(box)
        self.set_size_request(TILE_WIDTH, 120)
        self.set_tooltip_text(executable)
        self.connect("clicked", lambda _b: on_edit(executable, name))


class ProfileTile(Gtk.Box):
    """One profile's tile: its name, its summary line, and its actions.

    DETAILS closes the canvas and selects the profile in the main window —
    that is where bindings, DPI and lighting are edited, and a second editor
    would be a second place for the same rules (spec §2.7). Duplicate copies
    the profile whole, and Delete removes it. The desktop profile carries no
    actions that would remove it.
    """

    __gsignals__ = {
        "details": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "duplicate": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "delete": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, summary: ProfileSummary, *, deletable: bool):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._name = summary.name

        self.set_size_request(TILE_WIDTH, 120)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_valign(Gtk.Align.CENTER)
        label = Gtk.Label(label=summary.name, wrap=True)
        label.add_css_class("heading")
        box.append(label)
        line = profile_summary_line(summary)
        if line:
            detail = Gtk.Label(label=line, wrap=True)
            detail.add_css_class("caption")
            detail.add_css_class("dim-label")
            box.append(detail)
        self.append(box)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        actions.set_halign(Gtk.Align.CENTER)
        details = Gtk.Button(icon_name="document-edit-symbolic")
        details.set_tooltip_text(f"Edit {summary.name} in the main window")
        details.add_css_class("flat")
        details.connect("clicked", lambda _b: self.emit("details"))
        actions.append(details)

        duplicate = Gtk.Button(icon_name="edit-copy-symbolic")
        duplicate.set_tooltip_text(f"Copy {summary.name} to a new profile")
        duplicate.add_css_class("flat")
        duplicate.connect("clicked", lambda _b: self.emit("duplicate"))
        actions.append(duplicate)

        if deletable:
            delete = Gtk.Button(icon_name="user-trash-symbolic")
            delete.set_tooltip_text(f"Delete {summary.name}")
            delete.add_css_class("flat")
            delete.connect("clicked", lambda _b: self.emit("delete"))
            actions.append(delete)
        self.append(actions)

    @property
    def name(self) -> str:
        return self._name
