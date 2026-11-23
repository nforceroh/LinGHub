"""The LinGHub main window.

Shows the mouse diagram, the profile list, and the bindings of the selected
profile. Clicking a button in the table opens the binding editor; the change
goes to the daemon over D-Bus, which is the only writer of the config
(ADR-0004).
"""

from __future__ import annotations

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk

from .assignments import AssignmentsView
from .assignments.editor import BindingEditor
from .asyncbridge import run_and_report
from .buttonmap import describe
from .client import DaemonClient
from .daemon_write import DaemonWrite
from . import edit_apply
from .pending_edits import PendingEditsFor
from .profile_actions import ProfileActions
from .profiles import HomeCard, ManageProfiles, ProfileSelector
from .config_rail import ConfigRail
from .daemon_feed import DaemonFeed
from ..hardware.battery import battery, model_name
from ..daemon_view import DaemonView, ProfileSummary, ViewState
from . import presentation
from .. import version
from .device import DpiPanel
from .device import LedPanel
from .window_sizing import WANTED_SIZE, connect_first_map, preferred_size


logger = logging.getLogger("linghub.ui.window")


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, application, client: DaemonClient, schedule=run_and_report):
        super().__init__(application=application, title="LinGHub")
        self._client = client
        # One rule for every write: run, report, refresh. The reporter is
        # supplied per call because most writes report on the status line
        # and the profile prompts report in their own dialog.
        self._writes = DaemonWrite(self._refresh_now)
        # Every edit is held here until Save, so Discard can put the
        # window back to what the config says.
        self._pending = PendingEditsFor()
        # How a coroutine is put on the loop. Injected so a test can drive the
        # window on its own loop instead of patching this module's global.
        self._schedule = schedule
        self._state = ViewState()
        # Which profile the panels show. Deliberately separate from which
        # profile is loaded on the mouse: editing must not reconfigure it.
        self._editing: str | None = None
        self._bindings: dict[int, tuple[str, str]] = {}
        self._view: DaemonView | None = None
        self._refresh_task = None
        self._refresh_pending = False

        self.set_default_size(*preferred_size(WANTED_SIZE))
        connect_first_map(self)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="LinGHub", subtitle=""))
        self._title = header.get_title_widget()

        self._back_button = Gtk.Button(icon_name="go-previous-symbolic")
        self._back_button.set_tooltip_text("Back to the device")
        self._back_button.add_css_class("flat")
        self._back_button.connect("clicked", lambda _b: self._back_clicked())
        self._back_button.set_visible(False)
        header.pack_start(self._back_button)

        self._discard_button = Gtk.Button(label="Discard")
        self._discard_button.set_tooltip_text("Discard all unsaved changes")
        self._discard_button.add_css_class("flat")
        self._discard_button.connect("clicked", lambda _b: self._discard_changes())
        self._discard_button.set_sensitive(False)
        header.pack_end(self._discard_button)

        self._save_button = Gtk.Button(label="Apply")
        self._save_button.set_tooltip_text("Apply changes to the profile")
        self._save_button.add_css_class("suggested-action")
        self._save_button.connect("clicked", lambda _b: self._save_changes())
        self._save_button.set_sensitive(False)
        header.pack_end(self._save_button)

        # The selector lives in the header so it is present on every view: which
        # profile you are editing is context for all of them. It sits at the
        # right, before the menu, as the reference does.
        self._selector = ProfileSelector(
            on_chosen=self._choose_profile,
            on_manage=self._open_manage_profiles,
        )
        header.pack_end(self._selector)
        header.pack_end(self._build_main_menu())

        toolbar.add_top_bar(header)

        self._status = Gtk.Label(label="Connecting…")
        self._status.add_css_class("dim-label")
        self._status.set_margin_top(6)
        self._status.set_margin_bottom(6)
        toolbar.add_top_bar(self._status)

        # Shown only when the daemon runs code other than this window's.
        self._banner = Adw.Banner()
        toolbar.add_top_bar(self._banner)

        # The daemon's version, and the two things that report it: the banner
        # above and the About dialog's comments. The module owns the story;
        # the window owns the widgets it speaks through.
        self._feed = DaemonFeed(
            # A callable, not the client itself: the module calls it, and the
            # window's tests swap _client after construction.
            client=lambda: self._client,
            schedule=schedule,
            report=self._status.set_text,
            wanted_profile=self._editing_profile,
            apply_view=self._apply_view,
            current_version=version.current(),
            banner=self._banner,
        )

        # The profile management flows: prompts, validation and writes. The
        # window supplies its collaborators; the module owns the shape each
        # flow shares. Built after the status line, which its reports land on.
        self._actions = ProfileActions(
            self,
            # A callable, not the client itself: the window's tests swap
            # _client after construction, and the module must follow.
            lambda: self._client,
            self._writes,
            report=self._status.set_text,
            profile_names=lambda: self._state.profiles,
            desktop_profile=lambda: self._state.desktop_profile,
            profile_of_game=self._profile_of_game,
            on_async_error=self._on_async_error,
        )

        # Three views in one window: the home screen the window opens on, the
        # editor reached by clicking the mouse, and the manage-profiles canvas
        # reached from the selector. A stack rather than three windows, so
        # there is one place to refresh and one thing to manage.
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stack.add_named(self._build_home(), "home")
        self._stack.add_named(self._build_editor(), "editor")
        self._stack.add_named(self._build_manage(), "manage")

        toolbar.set_content(self._stack)
        self.set_content(toolbar)

        # No poll: the daemon announces every change the window shows, and
        # the client also reports the daemon starting or stopping.
        client.set_change_handler(self._on_daemon_change)
        self._feed.refresh()

    def _build_home(self) -> Gtk.Widget:
        """The home screen: the device card, centred on an empty canvas."""
        self._card = HomeCard()
        self._card.connect("configure", lambda _c: self._show_view("editor"))

        centre = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        centre.set_halign(Gtk.Align.CENTER)
        centre.set_valign(Gtk.Align.CENTER)
        centre.append(self._card)
        return centre

    def _build_manage(self) -> Gtk.Widget:
        """The manage-profiles canvas: games across the top, profiles below."""
        self._manage = ManageProfiles(
            on_add_game=self._prompt_add_game,
            on_edit_game=self._prompt_rename_game,
            on_details=self._canvas_details,
            on_duplicate=self._actions.prompt_duplicate_profile,
            on_delete=self._actions.prompt_delete_from_canvas,
        )
        return self._manage

    def _build_editor(self) -> Gtk.Widget:
        """The configuration screen: one rail and three configuration views."""
        # The stack before the rail: the rail selects a view as it is built,
        # and that selection lands in _show_config_view, which needs the
        # stack to exist.
        self._config_stack = Gtk.Stack()
        self._config_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._config_stack.add_named(self._build_assignments_view(), "assignments")
        self._config_stack.add_named(self._build_dpi_view(), "dpi")
        self._config_stack.add_named(self._build_lightsync_view(), "lightsync")
        self._config_stack.set_visible_child_name("assignments")

        self._config_rail = ConfigRail(
            on_view=self._show_config_view,
            on_manage=self._open_manage_profiles,
        )

        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        content.append(self._config_rail)
        content.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        content.append(self._config_stack)
        return content

    def _build_assignments_view(self) -> Gtk.Widget:
        """Assignments: command sidebar on the left, diagram and table on the right."""
        self._assignments = AssignmentsView(
            on_stage=self._on_assignment_staged,
            on_status=self._status.set_text,
            on_open_editor=self._open_editor,
        )
        return self._assignments

    def _build_panel_view(self, title: str, panel: Gtk.Widget) -> Gtk.Widget:
        """One configuration view: a heading over a panel, on a padded box."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(18)
        box.set_margin_bottom(18)
        box.set_margin_start(18)
        box.set_margin_end(18)
        label = Gtk.Label(label=title, xalign=0)
        label.add_css_class("heading")
        box.append(label)
        box.append(panel)
        return box

    def _build_dpi_view(self) -> Gtk.Widget:
        """The DPI view, moved out of the old full-width device row."""
        self._dpi_panel = DpiPanel(on_edited=self._stage_dpi_edit)
        return self._build_panel_view("Sensitivity (DPI)", self._dpi_panel)

    def _build_lightsync_view(self) -> Gtk.Widget:
        """The lighting view, moved out of the old full-width device row."""
        self._led_panel = LedPanel(on_edited=self._stage_led_edit)
        self._led_panel.set_hexpand(False)
        self._led_panel.set_halign(Gtk.Align.START)
        return self._build_panel_view("LIGHTSYNC", self._led_panel)

    # --- state -----------------------------------------------------------

    def refresh(self) -> None:
        """Read the daemon again, for a caller that knows something changed."""
        self._feed.refresh()

    def _on_daemon_change(self) -> None:
        GLib.idle_add(self._refresh_from_idle)

    def _refresh_from_idle(self) -> bool:
        self._feed.refresh()
        return GLib.SOURCE_REMOVE

    def _on_async_error(self, exc: Exception) -> None:
        self._status.set_text(f"Error: {exc}")

    async def _refresh_now(self) -> None:
        await self._feed.refresh_now()

    def _apply_daemon_version(self, daemon_version) -> None:
        """Remember the daemon's version, and flag it if it differs from ours."""
        self._feed.apply_daemon_version(daemon_version)

    def _build_main_menu(self) -> Gtk.MenuButton:
        """The header bar's menu, which holds About."""
        menu = Gio.Menu()
        menu.append("About LinGHub", "win.about")
        about = Gio.SimpleAction.new("about", None)
        about.connect("activate", lambda *_args: self._about_dialog().present(self))
        self.add_action(about)
        return Gtk.MenuButton(
            icon_name="open-menu-symbolic", menu_model=menu, tooltip_text="Main menu",
        )

    def _about_dialog(self) -> Adw.AboutDialog:
        """This window's app version, with the daemon's beside it."""
        return Adw.AboutDialog(
            application_name="LinGHub",
            version=version.current(),
            comments=f"Profile manager for the Logitech G502 family\n\n"
            f"{self._feed.about_comments()}",
        )

    def _apply_view(self, view: DaemonView) -> None:
        self._view = view
        self._state = view.state
        self._bindings = view.profile.bindings

        state = view.state
        if state.detected_game:
            self._title.set_subtitle(f"Playing {state.detected_game}")
        else:
            self._title.set_subtitle("No game detected")

        self._status.set_text(
            f"Active profile: {state.active_profile or 'unknown'}"
            f"   ·   Desktop: {state.desktop_profile}"
        )

        self._rebuild_profiles()
        self._rebuild_bindings()
        self._card.show_device(self._device_name(), battery())
        # Never reload a panel over unsaved edits: any change signal refreshes
        # the view, and would silently discard whatever the user is in the
        # middle of choosing.
        if not self._led_panel.dirty:
            self._led_panel.load(view.profile.leds)
        if not self._dpi_panel.dirty:
            self._dpi_panel.load(
                view.profile.resolutions,
                view.profile.report_rates,
                view.profile.report_rate,
            )
        self._sync_save_buttons()

    def _stage_dpi_edit(self, values) -> None:
        """Hold the DPI panel's values until the window's Apply is pressed.

        The panel reports dirty through its `on_edited` callback; the window
        records what the panel shows, so Apply writes what the user sees.
        """
        profile = self._editing_profile()
        if profile is None:
            return
        slots, rate = values
        edits = self._pending.for_profile(profile)
        edits.set_resolutions(slots, rate)
        self._sync_save_buttons()
        self._status.set_text("Resolution changes pending — press Apply.")

    def _sync_save_buttons(self) -> None:
        """Enable Save and Discard only when something is pending."""
        dirty = self._pending.dirty
        self._save_button.set_sensitive(dirty)
        self._discard_button.set_sensitive(dirty)

    def _save_changes(self) -> None:
        """Write every pending edit for the profile being edited."""
        profile = self._editing_profile()
        if profile is None:
            return
        run_and_report(self._do_save(profile), self._on_async_error)

    async def _do_save(self, profile: str) -> None:
        """Flush the pending edits in one write, then settle the panels.

        The daemon writes the config and pushes it to the mouse on its next
        tick, so there is no second step here: saving the config is saving the
        profile.
        """
        edits = self._pending.for_profile(profile)

        async def change() -> bool:
            rejected = await edit_apply.apply(edits, self._client)
            if rejected is not None:
                self._status.set_text(rejected)
                return False
            return True

        def settle() -> None:
            # Only now do the panels accept their values as the baseline, so a
            # failed save leaves the edits intact and still worth retrying.
            if edits.has_resolutions:
                self._dpi_panel.mark_saved()
            if edits.has_leds:
                self._led_panel.mark_saved()
            self._pending.clear()
            self._sync_save_buttons()

        await self._writes.run(
            change,
            report=self._status.set_text,
            failure=f"Could not save {profile}",
            success=f"Saved {profile}. The mouse updates within a couple of seconds.",
            on_success=settle,
        )

    def _discard_changes(self) -> None:
        """Throw away every pending edit and show the config as it is."""
        self._pending.clear()
        self._dpi_panel.revert()
        self._led_panel.revert()
        self._sync_save_buttons()
        self._status.set_text("Discarded unsaved changes.")
        # Reload from the daemon rather than from a remembered snapshot: the
        # config may have changed elsewhere while these edits were pending.
        self._feed.refresh()

    def _stage_led_edit(self, values) -> None:
        """Hold the lighting panel's values until Apply is pressed.

        The shape of a LED row (mode, brightness, duration, color) belongs to
        the panel; the window only forwards it, so the unpack happens there.
        """
        profile = self._editing_profile()
        if profile is None:
            return
        self._pending.for_profile(profile).set_leds(*values)
        self._sync_save_buttons()
        self._status.set_text("Lighting changes pending — press Apply.")

    def _device_name(self) -> str:
        """The mouse's name, as the card shows it.

        The kernel's hidpp power-supply entry carries the full model name, and
        the daemon publishes none of its own. A wired mouse has no such entry,
        so the fallback is the generic name rather than nothing.
        """
        return model_name() or "Logitech G502"

    def _rebuild_profiles(self) -> None:
        """Make the selector match the daemon's state.

        The selector updates its rows in place, so a refresh does not destroy
        the user's place in the list.
        """
        self._selector.show_profiles(
            self._state.profiles,
            active=self._state.active_profile,
            editing=self._editing_profile(),
        )

    def _rebuild_bindings(self) -> None:
        """Fill in what each button does, and highlight the selected row."""
        profile = self._editing_profile()
        pending = (
            self._pending.for_profile(profile).bindings if profile else {}
        )
        self._assignments.refresh(self._bindings, pending)

    # --- profile management ----------------------------------------------

    def _on_assignment_staged(self, index: int, kind: str, value) -> None:
        """The view staged an assignment; record it for the profile being edited."""
        profile = self._editing_profile()
        if profile is None:
            self._status.set_text("Select a profile first.")
            return
        self._start_binding_write(profile, index, kind, value)
        self._rebuild_bindings()

    def _open_editor(self, index: int, kind: str, value) -> None:
        """Open the binding editor for one button.

        The view owns the click; the window owns the dialog's parent and what
        an applied edit is worth. The editor closes on a truthy answer, so
        staging answers immediately: the edit is recorded, not written.
        """
        if not self._state.profiles:
            self._status.set_text("No profile to edit.")
            return
        profile = self._editing_profile()
        if profile is None:
            self._status.set_text("Select a profile first.")
            return
        BindingEditor(
            parent=self,
            button_index=index,
            kind=kind,
            value=value,
            on_apply=lambda i, k, v: self._start_binding_write(profile, i, k, v),
        ).present()

    def _editing_profile(self) -> str | None:
        """The profile the panels show and edit."""
        return presentation.editing_profile(self._state, self._editing)

    def _start_binding_write(self, profile: str, index: int, kind: str, value) -> bool:
        """Hold the binding until the window's Save is pressed.

        The editor closes on True, so this answers immediately: the edit is
        recorded, not written. Nothing reaches the daemon until Save, which is
        what makes Discard able to undo a binding change.
        """
        self._pending.for_profile(profile).set_binding(index, kind, value)
        self._sync_save_buttons()
        self._status.set_text(
            f"{describe(index)} pending — press Apply."
        )
        return True

    # --- interaction -----------------------------------------------------

    def _choose_profile(self, name: str) -> None:
        """Choose a profile from the selector, and load it onto the mouse.

        Choosing and loading are one action now. The old window had two — a
        list that chose what to edit and a `Load` button that put it on the
        mouse — and that distinction is the thing users are least likely to
        expect.

        Switching with unsaved changes asks first: the pending edits belong to
        the profile being left, and holding them for several profiles at once
        would mean two places remembering what the config says.
        """
        if name == self._editing:
            return
        if self._pending.dirty:
            self._confirm_switch(name, proceed=self._apply_selection)
            return
        self._apply_selection(name)

    def _show_view(self, name: str) -> None:
        """Swap between the home, manage and configuration screens."""
        self._stack.set_visible_child_name(name)
        self._back_button.set_visible(name != "home")
        if name == "editor":
            self._show_config_view("assignments")

    def _show_config_view(self, name: str) -> None:
        """Choose one of the three configuration views."""
        self._config_stack.set_visible_child_name(name)
        # The rail is built after the stack, and its initial select() lands
        # here while its own attribute is still unassigned.
        rail = getattr(self, "_config_rail", None)
        if rail is not None:
            rail.select(name)

    def _open_manage_profiles(self) -> None:
        """Open the manage-profiles canvas.

        The canvas is a view in this window, not a separate one: one source
        of truth, one place to refresh. Opening it with edits pending asks
        first, reusing the switch-profile prompt — it is the same question,
        because leaving the profile being edited behind is what both do
        (spec §2.7).
        """
        if self._pending.dirty:
            self._confirm_switch_for_canvas()
            return
        self._show_canvas()

    # --- canvas actions --------------------------------------------------

    def _fill_canvas(self, view: DaemonView) -> None:
        """Fill the canvas from a view, if one has been read.

        A daemon from before the canvas publishes no summaries, so the tiles
        are built from the profile names alone: name-only tiles are what a
        user can act on, and the summary line arrives when the daemon does.
        """
        if view is None or self._manage is None:
            return
        summaries = view.summaries or tuple(
            ProfileSummary(name=name) for name in view.state.profiles
        )
        self._manage.show(summaries, view.state.desktop_profile)

    # The two game prompts open the canvas's own dialog, so they stay here:
    # they need the canvas widget and the view's profile list, both of which
    # are the window's. The write they trigger belongs to ProfileActions.

    def _prompt_add_game(self) -> None:
        """Add a game: the executable to match, a name, and its profile."""
        self._manage.open_add_game(
            self,
            self._state.profiles,
            self._actions.create_game_profile,
        )

    def _prompt_rename_game(self, executable: str, name: str) -> None:
        """Rename a game's display name, by re-opening the dialog filled in.

        The dialog's callback takes (executable, name, profile); editing
        never moves the game between profiles, so the profile arrives empty
        and the owning profile is looked up from the view.
        """
        self._manage.open_edit_game(
            self, executable, name,
            self._state.profiles,
            lambda _exec, new_name, _profile:
                self._actions.rename_game(executable, new_name.strip()),
        )

    def _profile_of_game(self, executable: str) -> str | None:
        """The profile carrying this game, from the last view read."""
        if self._view is None:
            return None
        for summary in self._view.summaries:
            for game_executable, _name in summary.games:
                if game_executable.casefold() == executable.casefold():
                    return summary.name
        return None

    def _canvas_details(self, name: str) -> None:
        """Close the canvas and edit the profile, without loading it.

        The main window is where bindings, DPI and lighting are edited; a
        second editor would be a second place for the same rules. Editing
        deliberately does not load: DETAILS is an edit-side action, and
        taking over the mouse is the selector's job (spec §2.7).
        """
        if self._pending.dirty:
            self._confirm_switch(name, proceed=self._edit_without_loading)
            return
        self._edit_without_loading(name)

    def _edit_without_loading(self, name: str) -> None:
        self._editing = name
        self._pending.clear()
        self._sync_save_buttons()
        self._stack.set_visible_child_name("editor")
        self._back_button.set_visible(True)
        self._status.set_text(f"Editing {name} (not loaded).")
        self._rebuild_profiles()
        self._feed.refresh()

    def _confirm_unsaved(self, body, *, on_cancel, on_discard, on_save) -> None:
        """Ask what to do with unsaved changes before a navigation.

        One dialog for every destination — the canvas, another profile,
        editing without loading. The question and its three answers are
        always the same; only the body text and what each answer does vary,
        so those are what a caller supplies.
        """
        present_unsaved_dialog(
            self,
            body,
            on_cancel=on_cancel,
            on_discard=on_discard,
            on_save=on_save,
            report_error=self._on_async_error,
        )

    def _confirm_switch_for_canvas(self) -> None:
        """Ask what to do with unsaved changes before opening the canvas."""
        self._confirm_unsaved(
            f"Apply your changes to {self._editing} before managing profiles?",
            on_cancel=lambda: None,
            on_discard=self._show_canvas,
            on_save=lambda: self._save_then(self._show_canvas),
        )

    def _show_canvas(self) -> None:
        if self._view is None:
            self._status.set_text("Waiting for the daemon profile view.")
            return
        self._fill_canvas(self._view)
        self._stack.set_visible_child_name("manage")
        self._back_button.set_visible(True)

    def _back_clicked(self) -> None:
        """Return from wherever we are, without changing the selection."""
        if self._stack.get_visible_child_name() == "manage":
            # Leaving the canvas does not touch the editing profile: the
            # canvas is a place you navigate to, so its way back is not
            # "pick something" (spec §2.7).
            self._stack.set_visible_child_name("editor")
            self._back_button.set_visible(True)
            return
        self._show_view("home")

    def _apply_selection(self, name: str) -> None:
        """Show `name` in the panels and put it on the mouse.

        The refresh happens regardless of the load's outcome. Editing a profile
        that is not on the mouse is a legitimate state — the whole point of
        separating edit from load — so the panels must follow `_editing` even
        when the daemon refuses the write. Refreshing only on success would
        leave them showing the previous profile's bindings under the new one's
        name.
        """
        self._editing = name
        self._pending.clear()
        self._sync_save_buttons()
        self._status.set_text(f"Loading {name}…")
        self._feed.refresh()
        # Through the injected scheduler, like the refresh: a test drives its
        # own loop, and the GTK bridge would never run there.
        self._schedule(self._load_profile(name), self._on_async_error)

    def _confirm_switch(self, name: str, *, proceed) -> None:
        """Ask what to do with unsaved changes before switching profiles.

        `proceed` is the destination action itself — load the profile, or
        edit it without loading — so the prompt has no flag to branch on and
        every answer does what its caller came to do.
        """
        self._confirm_unsaved(
            f"Apply your changes to {self._editing} before switching to {name}?",
            on_cancel=self._reselect_current,
            on_discard=lambda: proceed(name),
            on_save=lambda: self._save_then(lambda: proceed(name)),
        )

    async def _save_then(self, proceed) -> None:
        """Save the pending edits, then `proceed` only if the save succeeded."""
        profile = self._editing_profile()
        if profile is None:
            return
        await self._do_save(profile)
        if self._pending.dirty:
            # The save was refused; stay where the edits are.
            self._reselect_current()
            return
        proceed()

    def _reselect_current(self) -> None:
        """Put the selector back on the profile still being edited.

        The selector is a dropdown, so there is no row to re-highlight: its
        label is derived from `_editing`, and re-showing the profiles is what
        puts it back.
        """
        self._rebuild_profiles()

    async def _load_profile(self, name: str) -> None:
        async def change() -> bool:
            return await self._client.load_profile(name)

        await self._writes.run(
            change,
            report=self._status.set_text,
            failure=f"Could not load {name}",
            rejected=f"The daemon refused to load {name}.",
            success=f"Loaded {name}.",
        )



def present_unsaved_dialog(parent, body, *, on_cancel, on_discard, on_save, report_error):
    """Ask what to do with unsaved changes: Cancel, Discard, or Apply.

    The dialog knows nothing about profiles or the daemon; the answers are
    whatever the caller decided each one should do, and the Apply answer may
    be a coroutine, which is reported through `report_error`.
    """
    dialog = Adw.MessageDialog(
        transient_for=parent,
        heading="Unsaved changes",
        body=body,
    )
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("discard", "Discard")
    dialog.add_response("save", "Apply")
    dialog.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
    dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("save")
    dialog.set_close_response("cancel")

    def on_response(_dialog, response):
        dialog.close()
        if response == "cancel":
            on_cancel()
        elif response == "discard":
            on_discard()
        elif response == "save":
            run_and_report(on_save(), report_error)

    dialog.connect("response", on_response)
    dialog.present()
