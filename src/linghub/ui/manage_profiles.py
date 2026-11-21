"""The manage-profiles canvas: games across the top, profiles below.

It is a view inside the main window, not a separate window and not a dialog:
swapping one window's content keeps one source of truth and one place to
refresh (spec §2.7). The games row navigates — clicking a game tile re-opens
the add-game dialog, which is how a display name is renamed — and the profiles
row is where profiles are added, duplicated and deleted, so the destructive
actions live away from the selector.

`PROFILES` is the only tab. The reference's `MACROS`, `INTEGRATIONS` and
`SETTINGS` tabs have no counterpart: there are no macros, no integrations, and
settings live in the config file. A tab bar with three dead tabs is worse than
no tab bar.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk

from ..daemon_view import ProfileSummary
from .add_game_dialog import AddGameDialog
from .manage_tile import AddTile, GameTile, ProfileTile


class ManageProfiles(Gtk.ScrolledWindow):
    """The canvas: a games row, a profiles row, and the actions on them.

    Emits nothing itself; every action is a callback given at construction,
    because the window owns the daemon writes and the navigation.
    """

    def __init__(
        self, on_add_game, on_edit_game, on_details,
        on_add_profile, on_duplicate, on_delete,
    ):
        super().__init__()
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.set_propagate_natural_height(True)

        self._on_add_game = on_add_game
        self._on_edit_game = on_edit_game
        self._on_details = on_details
        self._on_add_profile = on_add_profile
        self._on_duplicate = on_duplicate
        self._on_delete = on_delete

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        page.set_margin_top(18)
        page.set_margin_bottom(18)
        page.set_margin_start(18)
        page.set_margin_end(18)
        self.set_child(page)

        page.append(self._heading("Games"))

        self._games_row = Gtk.FlowBox()
        self._games_row.set_selection_mode(Gtk.SelectionMode.NONE)
        self._games_row.set_max_children_per_line(8)
        self._games_row.set_min_children_per_line(1)
        self._games_row.set_column_spacing(8)
        self._games_row.set_row_spacing(8)
        self._games_row.set_homogeneous(False)
        page.append(self._games_row)

        self._profiles_heading = self._heading("Profiles")
        page.append(self._profiles_heading)

        self._profiles_row = Gtk.FlowBox()
        self._profiles_row.set_selection_mode(Gtk.SelectionMode.NONE)
        self._profiles_row.set_max_children_per_line(8)
        self._profiles_row.set_min_children_per_line(1)
        self._profiles_row.set_column_spacing(8)
        self._profiles_row.set_row_spacing(8)
        self._profiles_row.set_homogeneous(False)
        page.append(self._profiles_row)

        self._game_tiles: dict[str, GameTile] = {}
        self._profile_tiles: dict[str, ProfileTile] = {}
        self._add_profile_tile = AddTile("+ ADD PROFILE")
        self._add_profile_tile.clicked(self._on_add_profile)
        self._add_game_tile = AddTile("+ ADD GAME")
        self._add_game_tile.clicked(self._on_add_game)

    @staticmethod
    def _heading(text: str) -> Gtk.Label:
        label = Gtk.Label(label=text, xalign=0)
        label.add_css_class("title-4")
        return label

    def show(
        self, summaries: tuple[ProfileSummary, ...], desktop_profile: str
    ) -> None:
        """Fill both rows from one read.

        The games row lists every game of every profile, so a game is
        reachable without first finding its profile. The profiles row lists
        every profile; filtering by the selected game is navigation the
        reference shows, but with a handful of profiles it hides profiles the
        user came to find, so everything is shown and the game click acts on
        the game itself.
        """
        self._fill_games(summaries)
        self._fill_profiles(summaries, desktop_profile)

    def _fill_games(self, summaries: tuple[ProfileSummary, ...]) -> None:
        seen: dict[str, str] = {}
        for summary in summaries:
            for executable, name in summary.games:
                seen.setdefault(executable, name)

        # Empty the row and refill it: a FlowBox child's position is its
        # insertion order, and updating in place would leave stale tiles
        # where games used to be.
        while True:
            child = self._games_row.get_first_child()
            if child is None:
                break
            self._games_row.remove(child)
        self._game_tiles.clear()

        self._games_row.insert(self._add_game_tile, 0)
        for position, (executable, name) in enumerate(seen.items(), start=1):
            tile = GameTile(executable, name, on_edit=self._on_edit_game)
            self._game_tiles[executable] = tile
            self._games_row.insert(tile, position)

    def _fill_profiles(
        self, summaries: tuple[ProfileSummary, ...], desktop_profile: str
    ) -> None:
        while True:
            child = self._profiles_row.get_first_child()
            if child is None:
                break
            self._profiles_row.remove(child)
        self._profile_tiles.clear()

        self._profiles_row.insert(self._add_profile_tile, 0)
        for position, summary in enumerate(summaries, start=1):
            tile = ProfileTile(summary, deletable=summary.name != desktop_profile)
            self._profile_tiles[summary.name] = tile
            tile.connect("details", lambda _t, name=summary.name: self._on_details(name))
            tile.connect(
                "duplicate", lambda _t, name=summary.name: self._on_duplicate(name)
            )
            tile.connect(
                "delete", lambda _t, name=summary.name: self._on_delete(name)
            )
            self._profiles_row.insert(tile, position)

        self._profiles_heading.set_text(
            f"Profiles ({len(summaries)})"
        )

    # --- dialogs ---------------------------------------------------------

    def open_add_game(
        self, widget: Gtk.Widget, profile_names: tuple[str, ...], on_accept
    ) -> None:
        """Present the add-game dialog, empty, for a new game."""
        dialog = AddGameDialog(
            self.get_root() or widget, profile_names, on_accept
        )
        dialog.present()

    def open_edit_game(
        self, widget: Gtk.Widget, executable: str, name: str,
        profile_names: tuple[str, ...], on_accept,
    ) -> None:
        """Present the dialog again, filled in, to rename a game."""
        dialog = AddGameDialog(
            self.get_root() or widget, profile_names, on_accept, editing=True
        )
        dialog._executable.set_text(executable)
        dialog._name.set_text(name)
        dialog.present()
