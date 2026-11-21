"""The LinGHub main window.

Shows the mouse diagram, the profile list, and the bindings of the selected
profile. Clicking a button in the table opens the binding editor; the change
goes to the daemon over D-Bus, which is the only writer of the config
(ADR-0004).
"""

from __future__ import annotations

import logging
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk

from .asyncbridge import run_and_report
from .binding_editor import BindingEditor
from .buttonmap import BUTTONS, DIAGRAM_IMAGE, describe, manual_number
from .client import DaemonClient
from ..daemon_view import DaemonView, ViewState
from .diagram import MouseDiagram
from . import presentation
from .. import version
from .dpi_panel import DpiPanel
from .led_panel import LedPanel


logger = logging.getLogger("linghub.ui.window")

# Shipped inside the package, so a wheel and an RPM find it the same way.
IMAGE = DIAGRAM_IMAGE


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, application, client: DaemonClient, schedule=run_and_report):
        super().__init__(application=application, title="LinGHub")
        self._client = client
        # How a coroutine is put on the loop. Injected so a test can drive the
        # window on its own loop instead of patching this module's global.
        self._schedule = schedule
        self._state = ViewState()
        self._selected_button: int | None = None
        # Which profile the panels show. Deliberately separate from which
        # profile is loaded on the mouse: editing must not reconfigure it.
        self._editing: str | None = None
        self._bindings: dict[int, tuple[str, str]] = {}
        self._profile_rows: dict[str, Adw.ActionRow] = {}
        self._led_panel: LedPanel | None = None
        self._dpi_panel: DpiPanel | None = None
        self._view: DaemonView | None = None
        self._refresh_task = None
        self._refresh_pending = False
        self._daemon_version = version.DaemonVersion.not_running()

        self.set_default_size(980, 620)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="LinGHub", subtitle=""))
        self._title = header.get_title_widget()
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

        toolbar.set_content(self._build_content())
        self.set_content(toolbar)

        # No poll: the daemon announces every change the window shows, and
        # the client also reports the daemon starting or stopping.
        client.set_change_handler(self._on_daemon_change)
        self._refresh()

    def _build_content(self) -> Gtk.Widget:
        split = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        split.set_position(600)
        split.set_wide_handle(True)

        split.set_start_child(self._build_diagram_pane())
        split.set_end_child(self._build_side_pane())
        return split

    def _build_diagram_pane(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)

        if IMAGE.exists():
            self._diagram = MouseDiagram(str(IMAGE))
            self._diagram.connect("button-selected", self._on_button_selected)
            frame = Gtk.Frame()
            frame.set_child(self._diagram)
            box.append(frame)
        else:
            self._diagram = None
            box.append(Gtk.Label(label=f"Diagram not found: {IMAGE}"))

        self._button_detail = Gtk.Label(label="Select a button on the diagram")
        self._button_detail.add_css_class("dim-label")
        self._button_detail.set_margin_top(12)
        box.append(self._button_detail)
        return box

    def _build_side_pane(self) -> Gtk.Widget:
        """Profiles, buttons and lighting, sharing the height between them.

        A plain box would let the last child take whatever it needs and squash
        the rest, which left the button table showing a single row. A Paned
        gives each section a share the user can adjust.
        """
        paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        paned.set_wide_handle(True)

        # --- profiles + buttons share the top ---
        top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        top.set_margin_top(12)
        top.set_margin_start(12)
        top.set_margin_end(12)

        profile_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        heading = self._section_label("Profiles")
        heading.set_hexpand(True)
        profile_header.append(heading)

        self._new_profile_button = Gtk.Button(icon_name="list-add-symbolic")
        self._new_profile_button.set_tooltip_text("Add a profile")
        self._new_profile_button.add_css_class("flat")
        self._new_profile_button.connect("clicked", lambda _b: self._prompt_new_profile())
        profile_header.append(self._new_profile_button)

        self._rename_profile_button = Gtk.Button(icon_name="document-edit-symbolic")
        self._rename_profile_button.set_tooltip_text("Rename the selected profile")
        self._rename_profile_button.add_css_class("flat")
        self._rename_profile_button.connect("clicked", lambda _b: self._prompt_rename_profile())
        profile_header.append(self._rename_profile_button)

        self._delete_profile_button = Gtk.Button(icon_name="user-trash-symbolic")
        self._delete_profile_button.set_tooltip_text("Delete the selected profile")
        self._delete_profile_button.add_css_class("flat")
        self._delete_profile_button.connect("clicked", lambda _b: self._prompt_delete_profile())
        profile_header.append(self._delete_profile_button)

        # Loading is its own action: selecting a profile only chooses what to
        # edit, so this is how you put one on the mouse.
        self._load_profile_button = Gtk.Button(label="Load")
        self._load_profile_button.set_tooltip_text("Load the selected profile onto the mouse")
        self._load_profile_button.add_css_class("flat")
        self._load_profile_button.connect("clicked", lambda _b: self._load_selected())
        profile_header.append(self._load_profile_button)

        top.append(profile_header)

        self._profile_list = Gtk.ListBox()
        self._profile_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._profile_list.connect("row-selected", self._on_profile_row_selected)
        profile_scroller = Gtk.ScrolledWindow()
        profile_scroller.set_child(self._profile_list)
        profile_scroller.set_min_content_height(120)
        profile_scroller.set_propagate_natural_height(True)
        top.append(profile_scroller)

        top.append(self._section_label("Buttons"))
        table_scroller = Gtk.ScrolledWindow()
        table_scroller.set_child(self._build_button_table())
        table_scroller.set_vexpand(True)
        top.append(table_scroller)

        paned.set_start_child(top)

        # --- lighting below, scrollable so it never squeezes the table ---
        lighting = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        lighting.set_margin_start(12)
        lighting.set_margin_end(12)
        lighting.set_margin_top(8)
        lighting.set_margin_bottom(12)
        lighting.append(self._section_label("DPI and report rate"))
        self._dpi_panel = DpiPanel(on_save=self._on_dpi_saved)
        lighting.append(self._dpi_panel)
        lighting.append(Gtk.Separator())

        lighting.append(self._section_label("Lighting"))
        self._led_panel = LedPanel(on_save=self._on_led_saved)
        lighting.append(self._led_panel)

        lighting_scroller = Gtk.ScrolledWindow()
        lighting_scroller.set_child(lighting)
        lighting_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        paned.set_end_child(lighting_scroller)

        paned.set_position(380)
        return paned

    def _build_button_table(self) -> Gtk.Widget:
        """Every button: manual number, function and ratbag index.

        The diagram labels circles with ratbag indices, so `Ratbag` is the
        column to read against the picture. `Manual` is only there to help
        someone holding the printed manual.
        """
        grid = Gtk.Grid()
        grid.set_column_spacing(18)
        grid.set_row_spacing(6)
        grid.set_margin_top(6)

        titles = ("Manual", "Function", "Does", "Ratbag")
        for column, title in enumerate(titles):
            label = Gtk.Label(label=title, xalign=0 if column != 3 else 1)
            label.add_css_class("dim-label")
            label.add_css_class("caption")
            grid.attach(label, column, 0, 1, 1)

        self._table_rows: dict[int, Gtk.Widget] = {}
        self._binding_rows: dict[int, Gtk.Widget] = {}

        for row, spot in enumerate(BUTTONS, start=1):
            manual = Gtk.Label(label=manual_number(spot.index), xalign=0)
            manual.add_css_class("dim-label")
            function = Gtk.Label(label=describe(spot.index), xalign=0)
            function.set_hexpand(True)
            does = Gtk.Label(label="—", xalign=0)
            ratbag = Gtk.Label(label=str(spot.index), xalign=1)
            ratbag.add_css_class("dim-label")

            widgets = (manual, function, does, ratbag)
            for column, widget in enumerate(widgets):
                grid.attach(widget, column, row, 1, 1)

            # The whole row is the click target, so a narrow label is not the
            # only way to open the editor. A controller can only belong to one
            # widget, so each label gets its own.
            for widget in widgets:
                click = Gtk.GestureClick()
                click.connect(
                    "released",
                    lambda _g, _n, _x, _y, i=spot.index: self._open_editor(i),
                )
                widget.add_controller(click)

            self._table_rows[spot.index] = function
            self._binding_rows[spot.index] = does

        return grid

    def _section_label(self, text: str) -> Gtk.Label:
        label = Gtk.Label(label=text, xalign=0)
        label.add_css_class("heading")
        return label

    # --- state -----------------------------------------------------------

    def refresh(self) -> None:
        """Read the daemon again, for a caller that knows something changed."""
        self._refresh()

    def _on_daemon_change(self) -> None:
        GLib.idle_add(self._refresh_from_idle)

    def _refresh_from_idle(self) -> bool:
        self._refresh()
        return GLib.SOURCE_REMOVE

    def _on_async_error(self, exc: Exception) -> None:
        self._status.set_text(f"Error: {exc}")

    def _refresh(self) -> None:
        """Read the daemon once, coalescing requests that arrive mid-flight.

        Three triggers call this: opening the window or connecting, the
        daemon's change signals, and every successful write. A read already in flight means this request
        collapses into one repeat when it finishes, so a slow read cannot land
        after a newer one.
        """
        if self._refresh_task is not None and not self._refresh_task.done():
            self._refresh_pending = True
            return
        self._refresh_task = self._schedule(
            self._refresh_loop(), self._on_async_error
        )

    async def _refresh_now(self) -> None:
        """Refresh and wait for it, for callers whose message must survive.

        A write reports its outcome on the status line, and applying a view
        overwrites that line. The write path therefore has to let the refresh
        finish before it reports, or the user never sees the message.
        """
        self._refresh()
        if self._refresh_task is not None:
            await self._refresh_task

    async def _refresh_loop(self) -> None:
        while True:
            await self._read_and_apply()
            if not self._refresh_pending:
                return
            self._refresh_pending = False

    async def _read_and_apply(self) -> None:
        try:
            view = await self._client.get_view(self._editing_profile() or "")
        except (RuntimeError, OSError) as exc:
            self._status.set_text(f"Daemon unavailable: {exc}")
            self._apply_daemon_version(version.DaemonVersion.not_running())
            return
        self._apply_view(view)
        # Read after the view, and on its own: a failure here must not cost
        # the user the state they came to see.
        try:
            daemon_version = await self._client.daemon_version()
        except (RuntimeError, OSError) as exc:
            logger.debug("cannot read the daemon's version: %s", exc)
            daemon_version = version.DaemonVersion.unreadable()
        self._apply_daemon_version(daemon_version)

    def _apply_daemon_version(self, daemon_version) -> None:
        """Remember the daemon's version, and flag it if it differs from ours."""
        self._daemon_version = daemon_version
        _line, note = version.describe(version.current(), daemon_version)
        self._banner.set_title(note or "")
        self._banner.set_revealed(note is not None)

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
        line, note = version.describe(version.current(), self._daemon_version)
        comments = line if note is None else f"{line}\n{note}"
        return Adw.AboutDialog(
            application_name="LinGHub",
            version=version.current(),
            comments=f"Profile manager for the Logitech G502 family\n\n{comments}",
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
        if self._led_panel is not None:
            # Never reload the panel over unsaved edits: any change signal
            # refreshes the view, and would silently discard whatever the user
            # is in the middle of choosing.
            if not self._led_panel.dirty:
                self._led_panel.load(view.profile.leds)
        if self._dpi_panel is not None and not self._dpi_panel.dirty:
            self._dpi_panel.load(
                view.profile.resolutions,
                view.profile.report_rates,
                view.profile.report_rate,
            )

    def _on_dpi_saved(self, slots: list, rate: int) -> None:
        """Persist the DPI panel's staged values when Save is pressed."""
        profile = self._editing_profile()
        if profile is None:
            return
        run_and_report(
            self._write_dpi(profile, slots, rate), self._on_async_error
        )

    async def _write_dpi(self, profile: str, slots: list, rate: int) -> None:
        async def change() -> bool:
            for index, (dpi, is_default, disabled) in enumerate(slots):
                if not await self._client.set_resolution(
                    profile, index, dpi,
                    make_default=is_default, disabled=disabled,
                ):
                    self._status.set_text(f"The daemon rejected DPI slot {index + 1}.")
                    return False
            if rate and not await self._client.set_report_rate(profile, rate):
                self._status.set_text("The daemon rejected that report rate.")
                return False
            return True

        if await self._daemon_write("Could not change the DPI", change):
            if self._dpi_panel is not None:
                self._dpi_panel.mark_saved()
            self._status.set_text(f"Updated the DPI of {profile}.")

    def _on_led_saved(self, mode: str, brightness: int, duration: int, color) -> None:
        """Persist the panel's staged values when Save is pressed."""
        profile = self._editing_profile()
        if profile is None:
            return
        run_and_report(
            self._write_leds(profile, mode, brightness, duration, color),
            self._on_async_error,
        )

    async def _write_leds(
        self, profile: str, mode: str, brightness: int, duration: int, color
    ) -> None:
        async def change() -> bool:
            return await self._client.set_leds(
                profile, mode, brightness, duration, color
            )

        if await self._daemon_write("Could not change the lighting", change):
            # Only now do the panel's values become the saved baseline, so a
            # failed write leaves the edits intact and still worth retrying.
            if self._led_panel is not None:
                self._led_panel.mark_saved()
            self._status.set_text(f"Updated the lighting of {profile}.")

    async def _daemon_write(self, failure: str, change) -> bool:
        """Run one daemon write and report the outcome on the status line.

        Run the change, turn a transport error or a `False` return into a
        status message, and only report success (and refresh) when the daemon
        accepted it. `change` reports its own rejection reason when it has a
        more specific one.
        """
        try:
            ok = await change()
        except (RuntimeError, OSError) as exc:
            self._status.set_text(f"{failure}: {exc}")
            return False
        if not ok:
            return False
        await self._refresh_now()
        return True

    async def _dialog_write(self, dialog, rejected: str, change) -> bool:
        """The same rule for writes whose failures belong in a dialog.

        Create and rename run from a prompt, so a rejection has to appear
        where the user typed, not on a status line behind the window.
        `rejected` is the message for a `False` return; a transport error is
        shown as its own text.
        """
        try:
            ok = await change()
        except (RuntimeError, OSError) as exc:
            dialog.show_error(str(exc))
            return False
        if not ok:
            dialog.show_error(rejected)
            return False
        dialog.close()
        await self._refresh_now()
        return True

    def _rebuild_profiles(self) -> None:
        """Make the profile list match the daemon's state, reusing rows.

        Rows are updated in place rather than recreated. Rebuilding the list
        on every refresh destroyed the user's selection, so clicking a
        profile appeared to bounce back to the first row.
        """
        rows = presentation.profile_rows(self._state, self._editing)
        names = [display.name for display in rows]

        # Drop rows for profiles that went away.
        existing = self._profile_rows
        for name in [name for name in existing if name not in names]:
            self._profile_list.remove(existing.pop(name))

        for position, display in enumerate(rows):
            name = display.name
            row = existing.get(name)
            if row is None:
                row = Adw.ActionRow(title=name)
                row.set_activatable(True)
                row._check = Gtk.Image.new_from_icon_name("object-select-symbolic")
                row.add_prefix(row._check)
                row._desktop = Gtk.Label(label="desktop")
                row.add_suffix(row._desktop)
                existing[name] = row
                self._profile_list.insert(row, position)

            row._check.set_visible(display.on_the_mouse)
            row.set_subtitle(display.subtitle)
            row._desktop.set_visible(display.is_desktop)

    def _rebuild_bindings(self) -> None:
        """Fill in what each button does, and highlight the selected row."""
        for index, widget in self._table_rows.items():
            if index == self._selected_button:
                widget.add_css_class("accent")
            else:
                widget.remove_css_class("accent")

            label = self._binding_rows.get(index)
            if label is not None:
                label.set_text(presentation.binding_label(self._bindings, index))

    # --- profile management ----------------------------------------------

    def _selected_profile(self) -> str | None:
        """The profile the list currently highlights."""
        row = self._profile_list.get_selected_row()
        return row.get_title() if row is not None else None

    def _prompt_new_profile(self) -> None:
        self._ask_for_text(
            title="New profile",
            label="Profile name",
            secondary="Game executable (optional)",
            on_accept=self._create_profile,
        )

    def _create_profile(self, name: str, executable: str, dialog) -> None:
        if not name.strip():
            dialog.show_error("A profile needs a name.")
            return
        run_and_report(
            self._do_create_profile(name.strip(), executable.strip(), dialog),
            self._on_async_error,
        )

    async def _do_create_profile(self, name: str, executable: str, dialog) -> None:
        async def change() -> bool:
            return await self._client.create_profile(name, executable)

        if await self._dialog_write(
            dialog, f"Cannot create {name!r}. The name may already be in use.", change
        ):
            self._status.set_text(f"Created profile {name}.")

    async def _do_rename_profile(self, old: str, new: str, dialog) -> None:
        if not new or new == old:
            dialog.show_error("Enter a different name.")
            return

        async def change() -> bool:
            return await self._client.rename_profile(old, new)

        if await self._dialog_write(
            dialog, f"Cannot rename to {new!r}. The name may be in use.", change
        ):
            self._status.set_text(f"Renamed {old} to {new}.")

    def _prompt_rename_profile(self) -> None:
        old = self._selected_profile()
        if old is None:
            self._status.set_text("Select a profile to rename.")
            return
        self._ask_for_text(
            title="Rename profile",
            label="New name",
            initial=old,
            on_accept=lambda new, _exec, dialog: run_and_report(
                self._do_rename_profile(old, new.strip(), dialog),
                self._on_async_error,
            ),
        )

    def _prompt_delete_profile(self) -> None:
        name = self._selected_profile()
        if name is None:
            self._status.set_text("Select a profile to delete.")
            return
        if name == self._state.desktop_profile:
            self._status.set_text("The desktop profile cannot be deleted.")
            return

        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=f"Delete {name}?",
            body="Its bindings, DPI and lighting settings are lost.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect(
            "response",
            lambda _d, response: (
                run_and_report(
                    self._do_delete_profile(name), self._on_async_error
                )
                if response == "delete"
                else None
            ),
        )
        dialog.present()

    async def _do_delete_profile(self, name: str) -> None:
        async def change() -> bool:
            return await self._client.delete_profile(name)

        if await self._daemon_write(f"Could not delete {name}", change):
            self._status.set_text(f"Deleted profile {name}.")

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

        dialog = Adw.MessageDialog(transient_for=self, heading=title, extra_child=box)
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

    def _open_editor(self, index: int) -> None:
        """Open the binding editor for one button."""
        if not self._state.profiles:
            self._status.set_text("No profile to edit.")
            return

        profile = self._editing_profile()
        if profile is None:
            self._status.set_text("Select a profile first.")
            return

        kind, value = self._bindings.get(index, ("disabled", None))
        BindingEditor(
            parent=self,
            button_index=index,
            kind=kind or "disabled",
            value=value,
            on_apply=lambda i, k, v: self._start_binding_write(profile, i, k, v),
        ).present()

    def _editing_profile(self) -> str | None:
        """The profile the panels show and edit."""
        return presentation.editing_profile(self._state, self._editing)

    def _start_binding_write(self, profile: str, index: int, kind: str, value) -> bool:
        """Kick off the write and report whether it was accepted.

        The editor needs an immediate answer so it can stay open on failure,
        so this reports optimistically and corrects the status line once the
        daemon replies.
        """
        run_and_report(
            self._write_binding(profile, index, kind, value),
            self._on_async_error,
        )
        return True

    async def _write_binding(self, profile: str, index: int, kind: str, value) -> None:
        async def change() -> bool:
            if kind == "disabled":
                return await self._client.clear_binding(profile, index)
            return await self._client.set_binding(profile, index, kind, str(value))

        if await self._daemon_write("Could not change the binding", change):
            self._status.set_text(f"Updated {describe(index)} in {profile}.")

    # --- interaction -----------------------------------------------------

    def _on_button_selected(self, _diagram, index: int) -> None:
        self._selected_button = index
        if self._diagram is not None:
            self._diagram.set_selected(index)
        self._button_detail.set_text(f"Selected: {describe(index)}")
        self._rebuild_bindings()

    def _on_profile_row_selected(self, _list, row) -> None:
        """Selecting a row chooses what to edit. It does not load anything."""
        if row is None:
            return
        self._select_profile(row.get_title())

    def _select_profile(self, name: str) -> None:
        """Make `name` the profile the panels show and edit."""
        if name == self._editing:
            return
        self._editing = name
        self._status.set_text(f"Editing {name}.")
        self._refresh()

    def _load_selected(self) -> None:
        """Load the selected profile onto the mouse. A deliberate action."""
        name = self._editing_profile()
        if name is None:
            self._status.set_text("Select a profile to load.")
            return
        run_and_report(self._load_profile(name), self._on_async_error)

    async def _load_profile(self, name: str) -> None:
        async def change() -> bool:
            return await self._client.load_profile(name)

        if await self._daemon_write(f"Could not load {name}", change):
            self._status.set_text(f"Loaded {name}.")
