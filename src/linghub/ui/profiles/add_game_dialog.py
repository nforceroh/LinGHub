"""The two-field dialog that adds a game: the executable to match, and the
name to call it.

The grilling (spec §2.7, Q31) rejected a file chooser because a Wine
executable's path — `C:\\Games\\…` — cannot be reached with a native file
dialog, which browses the Linux filesystem. The user then asked for a
filesystem browser anyway, so this dialog takes both: the path is an editable
field a Wine path can be typed into, with a Browse button beside it for the
executable that does live on this filesystem. The browse fills the field;
typing wins when they disagree.

It also asks for the profile the game belongs to, because in LinGHub a game
is owned by a profile and ADD GAME is the action that creates both.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk


class AddGameDialog(Adw.MessageDialog):
    """Ask for a game's executable, its display name, and its profile."""

    def __init__(self, parent, profile_names: tuple[str, ...], on_accept, *,
                 editing: bool = False):
        """Build the dialog.

        `editing=True` is the rename flow: the game already belongs to a
        profile, so the profile field is not shown and the callback receives
        (executable, name, profile) with the profile empty.
        """
        super().__init__(
            transient_for=parent, heading="Edit game" if editing else "Add a game"
        )
        self.set_body(
            "The game is matched against a running process's executable name. "
            "A Windows game under Wine is matched by its .exe filename."
        )
        self._on_accept = on_accept
        self._editing = editing

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)

        # The executable row: an editable field, because Wine paths cannot be
        # browsed, with Browse beside it for the ones that can.
        self._executable = Gtk.Entry()
        self._executable.set_placeholder_text("WorldOfTanks.exe")
        self._executable.set_activates_default(True)
        executable_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        executable_row.append(self._executable)
        browse = Gtk.Button(label="Browse…")
        browse.set_tooltip_text("Choose an executable from the filesystem")
        browse.connect("clicked", lambda _b: self._browse())
        executable_row.append(browse)
        box.append(self._label_for("Game executable"))
        box.append(executable_row)

        self._name = Gtk.Entry()
        self._name.set_placeholder_text("World of Tanks")
        box.append(self._label_for("Display name (optional)"))
        box.append(self._name)

        # The profile the game belongs to. New profiles are the common case,
        # so the entry starts free-form and existing names are offered as
        # completions rather than forced choices.
        self._profile = Gtk.Entry()
        self._profile.set_placeholder_text("A new profile's name")
        completion = Gtk.EntryCompletion()
        model = Gtk.ListStore(str)
        for name in profile_names:
            model.append([name])
        completion.set_model(model)
        completion.set_text_column(0)
        self._profile.set_completion(completion)
        # Editing does not move the game between profiles: it renames the
        # display name. Moving a game is a decision for a later version.
        if not editing:
            box.append(self._label_for("Profile"))
            box.append(self._profile)

        self.set_extra_child(box)
        self.add_response("cancel", "Cancel")
        self.add_response("ok", "Add")
        self.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        self.set_default_response("ok")
        self.set_close_response("cancel")
        self.connect("response", self._on_response)

    @staticmethod
    def _label_for(text: str) -> Gtk.Label:
        label = Gtk.Label(label=text, xalign=0)
        return label

    def _browse(self) -> None:
        """Open a file chooser for an executable on this filesystem.

        A native chooser cannot reach a Wine path, which is why the field
        stays editable; the chooser is for the executables that are real
        files here.
        """
        dialog = Gtk.FileDialog()
        dialog.set_title("Choose the game executable")

        def on_open(_dialog, result):
            try:
                file = dialog.open_finish(result)
            except Exception:
                return  # Cancelled.
            if file is not None:
                self._executable.set_text(file.get_path() or "")
                if not self._name.get_text().strip():
                    stem = file.get_basename()
                    if stem.lower().endswith(".exe"):
                        stem = stem[:-4]
                    self._name.set_text(stem)

        dialog.open(self.get_root(), None, on_open)

    def _on_response(self, _dialog, response) -> None:
        if response != "ok":
            self.close()
            return
        executable = self._executable.get_text().strip()
        profile = self._profile.get_text().strip()
        if not executable:
            self.show_error("A game needs an executable to match.")
            return
        if not profile and not self._editing:
            self.show_error("The game needs a profile to belong to.")
            return
        # The match is against the basename, so a Windows path is fine as-is;
        # the display name defaults to the executable, which the domain
        # already strips `.exe` from.
        name = self._name.get_text().strip()
        self.close()
        self._on_accept(executable, name, profile)

    def show_error(self, message: str) -> None:
        self.set_body(message)
        self.present()
