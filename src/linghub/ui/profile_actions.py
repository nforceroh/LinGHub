"""The profile management flows: rename, delete, duplicate, add game, rename game.

The window used to own these flows as methods, each restating the same shape:
prompt, validate, write through DaemonWrite, report. Six copies of the shape
lived interleaved with the window's navigation and refresh code, and their
tests built a half-constructed window to check one refusal message.

This module owns the flows. The window supplies what varies at construction —
the client, the write runner, where reports go, which profile is being edited,
and how to look up a game's profile — and then calls one method per user
action. The prompts and their validation rules are implementation.

The window keeps the unsaved-changes policy: nothing here decides whether a
switch should ask first.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk

from .asyncbridge import run_and_report


class ProfileActions:
    """The management flows for profiles and their games.

    Constructed once per window. The collaborators are injected because they
    are the window's own: the client, the DaemonWrite runner, the status
    line's reporter, and the lookups only the window's state can answer.
    """

    def __init__(
        self, parent, client, writes, *, report,
        profile_names, desktop_profile, profile_of_game, on_async_error,
    ):
        self._parent = parent
        # The client arrives as a zero-argument callable, so a test can swap
        # the window's client after this module was constructed.
        self._client = client
        self._writes = writes
        self._report = report
        self._profile_names = profile_names
        self._desktop_profile = desktop_profile
        self._profile_of_game = profile_of_game
        self._on_async_error = on_async_error

    # --- interface --------------------------------------------------------

    def prompt_delete_from_canvas(self, name: str) -> None:
        if name == self._desktop_profile():
            self._report("The desktop profile cannot be deleted.")
            return
        self._confirm_delete(
            name,
            body="Its bindings, DPI and lighting settings are lost, "
                 "along with its games.",
        )

    def prompt_duplicate_profile(self, name: str) -> None:
        self._ask_for_text(
            title=f"Duplicate {name}",
            label="New profile name",
            initial=f"{name} copy",
            on_accept=lambda new, _exec, dialog: run_and_report(
                self._duplicate_profile(name, new.strip(), dialog),
                self._on_async_error,
            ),
        )

    def create_game_profile(self, executable: str, name: str, profile: str) -> None:
        """Create the profile a new game belongs to, carrying the game.

        ADD GAME creates both: in LinGHub a game is owned by a profile, so a
        game with no profile left matches nothing. A profile name that is
        already in use is refused by the daemon and reported, not silently
        attached to the existing one.
        """
        profile = profile.strip()
        if profile in self._profile_names():
            self._report(
                f"Profile {profile!r} already exists; "
                "rename it or choose another name."
            )
            return
        run_and_report(
            self._create_game_profile(executable, name, profile),
            self._on_async_error,
        )

    def rename_game(self, executable: str, name: str) -> None:
        """Set a game's display name, reporting on the status line.

        The prompt has closed by the time the daemon answers, so its errors
        belong on the status line rather than in a dialog nobody is looking
        at.
        """
        profile = self._profile_of_game(executable)
        if profile is None:
            self._report(f"No profile carries {executable}.")
            return

        async def change() -> bool:
            return await self._client().rename_game(profile, executable, name)

        async def do():
            await self._writes.run(
                change,
                report=self._report,
                failure="Could not rename the game",
                rejected=f"Cannot rename {executable!r}.",
                success=f"Renamed the game to {name}.",
            )

        run_and_report(do(), self._on_async_error)

    # --- flows ------------------------------------------------------------

    async def _delete_profile(self, name: str) -> None:
        async def change() -> bool:
            return await self._client().delete_profile(name)

        await self._writes.run(
            change,
            report=self._report,
            failure=f"Could not delete {name}",
            success=f"Deleted profile {name}.",
        )

    async def _duplicate_profile(self, old: str, new: str, dialog) -> None:
        if not new:
            dialog.show_error("Enter a name for the copy.")
            return

        async def change() -> bool:
            return await self._client().duplicate_profile(old, new)

        await self._writes.run(
            change,
            report=dialog.show_error,
            failure="Could not duplicate the profile",
            rejected=f"Cannot name the copy {new!r}. The name may be in use.",
            success=f"Copied {old} to {new}.",
            on_success=dialog.close,
        )

    async def _create_game_profile(
        self, executable: str, name: str, profile: str
    ) -> None:
        async def change() -> bool:
            ok = await self._client().create_profile(profile, executable)
            if not ok:
                return False
            if name and name != executable:
                return await self._client().rename_game(profile, executable, name)
            return True

        await self._writes.run(
            change,
            report=self._report,
            failure="Could not add the game",
            rejected=(
                f"Cannot add {executable!r}. The profile name may be in use."
            ),
            success=f"Added {name or executable} to {profile}.",
        )

    # --- prompts ----------------------------------------------------------

    def _confirm_delete(self, name: str, *, body: str) -> None:
        dialog = Adw.MessageDialog(
            transient_for=self._parent,
            heading=f"Delete {name}?",
            body=body,
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect(
            "response",
            lambda _d, response: (
                run_and_report(
                    self._delete_profile(name), self._on_async_error
                )
                if response == "delete"
                else None
            ),
        )
        dialog.present()

    def _ask_for_text(
        self, *, title: str, label: str, on_accept, initial: str = "",
        secondary: str | None = None,
    ) -> None:
        """A small text prompt, reused by create and rename."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)

        entry = Gtk.Entry(text=initial)
        entry.set_activates_default(True)
        box.append(Gtk.Label(label=label, xalign=0))
        box.append(entry)

        extra = None
        if secondary is not None:
            extra = Gtk.Entry()
            box.append(Gtk.Label(label=secondary, xalign=0))
            box.append(extra)

        dialog = Adw.MessageDialog(
            transient_for=self._parent, heading=title, extra_child=box
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("ok", "OK")
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("ok")
        dialog.set_close_response("cancel")

        def on_response(_dialog, response):
            if response != "ok":
                dialog.close()
                return
            on_accept(entry.get_text(), extra.get_text() if extra else "", dialog)

        dialog.connect("response", on_response)
        dialog.present()
