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
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from .asyncbridge import run_and_report
from .binding_editor import BindingEditor
from .buttonmap import BUTTONS, DIAGRAM_IMAGE, describe, manual_number
from .client import DaemonClient
from .daemon_write import DaemonWrite
from .pending_edits import PendingEditsFor
from .profile_selector import ProfileSelector
from .home_card import HomeCard
from .manage_profiles import ManageProfiles
from .assignment_sidebar import AssignmentSidebar
from .config_rail import ConfigRail
from ..hardware.battery import battery, model_name
from ..daemon_view import DaemonView, ProfileSummary, ViewState
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
        self._selected_button: int | None = None
        # Which profile the panels show. Deliberately separate from which
        # profile is loaded on the mouse: editing must not reconfigure it.
        self._editing: str | None = None
        self._bindings: dict[int, tuple[str, str]] = {}
        self._led_panel: LedPanel | None = None
        self._dpi_panel: DpiPanel | None = None
        self._view: DaemonView | None = None
        self._refresh_task = None
        self._refresh_pending = False
        self._daemon_version = version.DaemonVersion.not_running()

        self.set_default_size(*self._preferred_size())
        self.connect("map", self._on_map)

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
        self._refresh()

    # The size the layout is designed for. Anything smaller and the bottom row
    # starts to scroll; anything larger is wasted space.
    WANTED_SIZE = (1140, 840)

    @classmethod
    def _preferred_size(cls) -> tuple[int, int]:
        """The window size to open at, clamped to the screen it opens on.

        The layout wants 1140x840, but a 1366x768 laptop has about 745 usable
        pixels of height, and a window taller than the screen hides its own
        bottom row. Asking for the layout's size and letting the monitor cap it
        keeps the window fully visible on any screen.
        """
        wanted_width, wanted_height = cls.WANTED_SIZE
        display = Gdk.Display.get_default()
        if display is None:
            return wanted_width, wanted_height
        monitors = display.get_monitors()
        if monitors.get_n_items() == 0:
            return wanted_width, wanted_height
        geometry = monitors.get_item(0).get_geometry()
        # Leave room for the desktop's own panels and the window's shadow.
        return (
            min(wanted_width, int(geometry.width * 0.92)),
            min(wanted_height, int(geometry.height * 0.88)),
        )

    def _on_map(self, _window) -> None:
        """Put the window fully on-screen the first time it is shown.

        The desktop remembers a window position per application id, and a
        position saved when the window's minimum width exceeded the screen
        keeps restoring half off-screen. Maximizing overrides it; the user
        can unmaximize to whatever size they want afterwards.
        """
        self._fit_to_screen()
        if not self.is_maximized():
            self.maximize()

    def _fit_to_screen(self) -> None:
        """Shrink a window that is larger than the screen it opened on.

        The desktop remembers a window's size per application id, so a size
        that was correct for an older, taller layout is restored over the
        default and can leave the window taller than the screen, hiding its own
        bottom row. The remembered size is only a starting point: if it does
        not fit, the screen wins.
        """
        surface = self.get_surface()
        display = Gdk.Display.get_default()
        if surface is None or display is None:
            return
        monitor = display.get_monitor_at_surface(surface)
        if monitor is None:
            return
        geometry = monitor.get_geometry()
        width, height = self.get_width(), self.get_height()
        if width <= geometry.width and height <= geometry.height:
            return
        self.set_default_size(
            min(width, int(geometry.width * 0.92)),
            min(height, int(geometry.height * 0.88)),
        )

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
            on_duplicate=self._prompt_duplicate_profile,
            on_delete=self._prompt_canvas_delete,
        )
        return self._manage

    def _build_editor(self) -> Gtk.Widget:
        """The configuration screen: one rail and three configuration views."""
        self._config_rail = ConfigRail(
            on_view=self._show_config_view,
            on_manage=self._open_manage_profiles,
        )

        self._config_stack = Gtk.Stack()
        self._config_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._config_stack.add_named(self._build_assignments_view(), "assignments")
        self._config_stack.add_named(self._build_dpi_view(), "dpi")
        self._config_stack.add_named(self._build_lightsync_view(), "lightsync")
        self._config_stack.set_visible_child_name("assignments")

        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        content.append(self._config_rail)
        content.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        content.append(self._config_stack)
        return content

    def _build_assignments_view(self) -> Gtk.Widget:
        """Assignments: command sidebar on the left, diagram and table on the right."""
        self._assignment_sidebar = AssignmentSidebar(
            on_chosen=self._on_assignment_chosen,
        )

        right = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        right.set_wide_handle(True)
        right.set_position(430)
        right.set_start_child(self._build_diagram_pane())

        table_scroller = Gtk.ScrolledWindow()
        table_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        table_scroller.set_vexpand(True)

        table_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        table_box.set_margin_top(8)
        table_box.set_margin_bottom(12)
        table_box.set_margin_start(12)
        table_box.set_margin_end(12)
        table_box.append(self._section_label("Bindings"))
        table_box.append(self._build_button_table())
        table_scroller.set_child(table_box)
        right.set_end_child(table_scroller)

        split = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        split.set_wide_handle(True)
        # 360px: wide enough for the four group tabs and the choice labels
        # to read without ellipsizing. Narrower defaults squeezed the tab row
        # and left every row caption cut off until the divider was dragged.
        split.set_position(390)
        split.set_start_child(self._assignment_sidebar)
        split.set_end_child(right)
        return split

    def _build_dpi_view(self) -> Gtk.Widget:
        """The DPI view, moved out of the old full-width device row."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(18)
        box.set_margin_bottom(18)
        box.set_margin_start(18)
        box.set_margin_end(18)
        box.append(self._section_label("Sensitivity (DPI)"))
        self._dpi_panel = DpiPanel(on_save=self._on_dpi_saved)
        box.append(self._dpi_panel)
        return box

    def _build_lightsync_view(self) -> Gtk.Widget:
        """The lighting view, moved out of the old full-width device row."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(18)
        box.set_margin_bottom(18)
        box.set_margin_start(18)
        box.set_margin_end(18)
        box.append(self._section_label("LIGHTSYNC"))
        self._led_panel = LedPanel(
            on_save=self._on_led_saved,
        )
        self._led_panel.set_hexpand(False)
        self._led_panel.set_halign(Gtk.Align.START)
        box.append(self._led_panel)
        return box

    def _build_diagram_pane(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)

        if IMAGE.exists():
            self._diagram = MouseDiagram(str(IMAGE))
            self._diagram.connect("button-selected", self._on_button_selected)
            self._diagram.connect("assignment-dropped", self._on_assignment_dropped)
            # No Frame: it drew a border and a filled background around the
            # image, which has a transparent background of its own. The image
            # sits directly in the pane, so the UI's background shows through.
            # Top-aligned: the image cannot grow to fill a tall pane without
            # distorting, so the space it leaves belongs at the bottom rather
            # than split above and below it.
            self._diagram.set_valign(Gtk.Align.START)
            box.append(self._diagram)
        else:
            self._diagram = None
            box.append(Gtk.Label(label=f"Diagram not found: {IMAGE}"))

        return box

    def _build_side_pane(self) -> Gtk.Widget:
        """Profiles, bindings, then DPI and lighting side by side.

        A plain vertical box, not a Paned: the sections have natural heights
        and nothing needs to stretch, so a draggable divider would only let
        the user drag one into a useless position. DPI and lighting share a
        row because together they are taller than the window.
        """
        pane = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        pane.set_margin_top(12)
        pane.set_margin_start(12)
        pane.set_margin_end(12)
        pane.set_margin_bottom(12)

        pane.append(self._build_profile_header())

        # The table is not in its own scroller: the whole pane scrolls as one,
        # so there is a single scrollbar and no section can be clipped to a
        # sliver while the pane still has room below it.
        pane.append(self._build_button_table())

        # One scrollbar for the pane. At the default window height everything
        # fits; on a shorter screen the pane scrolls rather than squeezing the
        # table into a two-row window.
        scroller = Gtk.ScrolledWindow()
        scroller.set_child(pane)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_propagate_natural_height(True)
        return scroller

    def _build_profile_header(self) -> Gtk.Widget:
        """The Bindings heading and the commit pair.

        The profile buttons that used to live here are gone: choosing a profile
        is the selector's job, and adding, renaming and deleting moved to the
        manage-profiles canvas. Apply and Discard stay, because they commit what
        you changed in the profile the selector chose.
        """
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        heading = self._section_label("Bindings")
        heading.set_hexpand(True)
        header.append(heading)

        self._discard_button = Gtk.Button(icon_name="edit-undo-symbolic")
        self._discard_button.set_tooltip_text("Discard all unsaved changes")
        self._discard_button.add_css_class("flat")
        self._discard_button.connect("clicked", lambda _b: self._discard_changes())
        self._discard_button.set_sensitive(False)
        header.append(self._discard_button)

        self._save_button = Gtk.Button(icon_name="document-save-symbolic")
        self._save_button.set_tooltip_text("Save all changes to the profile")
        self._save_button.add_css_class("suggested-action")
        self._save_button.connect("clicked", lambda _b: self._save_changes())
        self._save_button.set_sensitive(False)
        header.append(self._save_button)

        return header

    def _build_device_panels(self) -> Gtk.Widget:
        """DPI and lighting side by side, across the full window width.

        DPI carries five slot rows plus a rate dropdown; lighting carries four
        controls. DPI gets the larger share because its rows are the widest
        thing here, and lighting is left-aligned in what remains.
        """
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)
        row.set_margin_top(12)
        row.set_margin_bottom(12)
        row.set_margin_start(12)
        row.set_margin_end(12)

        dpi_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        dpi_box.set_hexpand(True)
        dpi_box.append(self._section_label("DPI and report rate"))
        self._dpi_panel = DpiPanel(on_save=self._on_dpi_saved)
        dpi_box.append(self._dpi_panel)
        row.append(dpi_box)

        led_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        led_box.set_hexpand(True)
        led_box.append(self._section_label("Lighting"))
        self._led_panel = LedPanel(on_save=self._on_led_saved)
        led_box.append(self._led_panel)
        row.append(led_box)

        # Not homogeneous: that would force 1:1 and squeeze the five DPI slot
        # rows. DPI expands into the slack and lighting keeps its natural
        # width, which is what the two panels actually need.
        dpi_box.set_hexpand(True)
        led_box.set_hexpand(False)
        return row

    def _build_button_table(self) -> Gtk.Widget:
        """Every button: manual number, function and ratbag index.

        The diagram labels circles with ratbag indices, so `Ratbag` is the
        column to read against the picture. `Manual` is only there to help
        someone holding the printed manual.
        """
        grid = Gtk.Grid()
        grid.set_column_spacing(18)
        # 2px between rows: eleven rows at 6px cost 66px of pure gap, and the
        # table is the tallest thing in the pane.
        grid.set_row_spacing(2)
        grid.set_margin_top(4)

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
            # No hexpand: it stretched the Function column across the pane and
            # pushed Does and Ratbag to the far edge, leaving a wide gap
            # between Function and Does. The columns now sit at their natural
            # widths, close together.
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
        wanted = self._editing_profile() or ""
        try:
            view = await self._client.get_view(wanted)
        except (RuntimeError, OSError) as exc:
            self._status.set_text(f"Daemon unavailable: {exc}")
            self._apply_daemon_version(version.DaemonVersion.not_running())
            return
        self._apply_view(view)
        # The first read has no state yet, so it cannot name a profile and asks
        # for "". That answer carries the profile list but no profile's
        # sections, so the panels would stay empty until something else
        # happened to trigger a read. Now that the state is known, read again
        # for the profile we should actually be editing.
        if not wanted and self._editing_profile():
            self._refresh_pending = True
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
        if hasattr(self, "_diagram") and self._diagram is not None:
            self._diagram.set_binding_labels(
                {
                    index: presentation.diagram_binding_label(self._bindings, index)
                    for index in [spot.index for spot in BUTTONS]
                }
            )
        self._card.show_device(self._device_name(), battery())
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
        self._sync_save_buttons()

    def _on_dpi_saved(self, slots: list, rate: int) -> None:
        """Hold the DPI panel's values until the window's Save is pressed."""
        profile = self._editing_profile()
        if profile is None:
            return
        self._pending.for_profile(profile).set_resolutions(slots, rate)
        self._sync_save_buttons()
        self._status.set_text("DPI changes pending — press Apply.")

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
            for index, edit in sorted(edits.bindings.items()):
                if edit.kind == "disabled":
                    ok = await self._client.clear_binding(profile, index)
                else:
                    ok = await self._client.set_binding(
                        profile, index, edit.kind, str(edit.value)
                    )
                if not ok:
                    self._status.set_text(f"The daemon rejected button {index}.")
                    return False

            if edits.resolutions is not None:
                for index, (dpi, is_default, disabled) in enumerate(edits.resolutions):
                    if not await self._client.set_resolution(
                        profile, index, dpi,
                        make_default=is_default, disabled=disabled,
                    ):
                        self._status.set_text(
                            f"The daemon rejected DPI preset {index + 1}."
                        )
                        return False

            if edits.report_rate is not None:
                if not await self._client.set_report_rate(profile, edits.report_rate):
                    self._status.set_text("The daemon rejected that report rate.")
                    return False

            if edits.leds is not None:
                leds = edits.leds
                if not await self._client.set_leds(
                    profile, leds["mode"], leds["brightness"],
                    leds["duration"], leds["color"],
                ):
                    self._status.set_text("The daemon rejected that lighting.")
                    return False
            return True

        def settle() -> None:
            # Only now do the panels accept their values as the baseline, so a
            # failed save leaves the edits intact and still worth retrying.
            if self._dpi_panel is not None and edits.resolutions is not None:
                self._dpi_panel.mark_saved()
            if self._led_panel is not None and edits.leds is not None:
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
        if self._dpi_panel is not None:
            self._dpi_panel.revert()
        if self._led_panel is not None:
            self._led_panel.revert()
        self._sync_save_buttons()
        self._status.set_text("Discarded unsaved changes.")
        # Reload from the daemon rather than from a remembered snapshot: the
        # config may have changed elsewhere while these edits were pending.
        self._refresh()

    def _on_led_saved(self, mode: str, brightness: int, duration: int, color) -> None:
        """Hold the lighting panel's values until the window's Save is pressed."""
        profile = self._editing_profile()
        if profile is None:
            return
        self._pending.for_profile(profile).set_leds(mode, brightness, duration, color)
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
        for index, widget in self._table_rows.items():
            if index == self._selected_button:
                widget.add_css_class("accent")
            else:
                widget.remove_css_class("accent")

            label = self._binding_rows.get(index)
            if label is not None:
                label.set_text(
                    presentation.binding_label(self._bindings, index, pending)
                )
        if hasattr(self, "_diagram") and self._diagram is not None:
            self._diagram.set_binding_labels(
                {
                    index: presentation.diagram_binding_label(self._bindings, index)
                    for index in [spot.index for spot in BUTTONS]
                }
            )

    # --- profile management ----------------------------------------------

    async def _do_rename_profile(self, old: str, new: str, dialog) -> None:
        if not new or new == old:
            dialog.show_error("Enter a different name.")
            return

        async def change() -> bool:
            return await self._client.rename_profile(old, new)

        await self._writes.run(
            change,
            report=dialog.show_error,
            failure="Could not rename the profile",
            rejected=f"Cannot rename to {new!r}. The name may be in use.",
            success=f"Renamed {old} to {new}.",
            on_success=dialog.close,
        )

    def _prompt_rename_profile(self) -> None:
        old = self._editing_profile()
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
        name = self._editing_profile()
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

        await self._writes.run(
            change,
            report=self._status.set_text,
            failure=f"Could not delete {name}",
            success=f"Deleted profile {name}.",
        )

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

    def _on_assignment_dropped(self, _diagram, index: int, choice) -> None:
        """A sidebar choice dropped on a hotspot assigns that button."""
        self._selected_button = index
        self._on_assignment_chosen(choice.kind, choice.value)
        self._rebuild_bindings()

    def _on_assignment_chosen(self, kind: str, value: object) -> None:
        """Stage a sidebar choice for the currently selected button."""
        if self._selected_button is None:
            self._status.set_text(
                "Select a button on the diagram or in the bindings table first."
            )
            return
        profile = self._editing_profile()
        if profile is None:
            self._status.set_text("Select a profile first.")
            return
        self._start_binding_write(
            profile, self._selected_button, kind, value
        )
        if kind == "disabled":
            assigned = "Nothing"
        else:
            from .binding_labels import describe_binding
            assigned = describe_binding(kind, value)
        self._status.set_text(
            f"{describe(self._selected_button)} will do {assigned} — press Apply."
        )

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

    def _on_button_selected(self, _diagram, index: int) -> None:
        self._selected_button = index
        if self._diagram is not None:
            self._diagram.set_selected(index)
        self._status.set_text(f"Selected: {describe(index)}")
        self._rebuild_bindings()

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
            self._confirm_switch(name)
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
        if hasattr(self, "_config_stack"):
            self._config_stack.set_visible_child_name(name)
        if hasattr(self, "_config_rail") and name in (
            "dpi", "assignments", "lightsync"
        ):
            self._config_rail.select(name)

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

    def _prompt_add_game(self) -> None:
        """Add a game: the executable to match, a name, and its profile."""
        self._manage.open_add_game(
            self,
            self._state.profiles,
            self._create_game_profile,
        )

    def _prompt_rename_game(self, executable: str, name: str) -> None:
        """Rename a game's display name, by re-opening the dialog filled in.

        The dialog's callback takes (executable, name, profile); editing
        never moves the game between profiles, so the profile arrives empty
        and the owning profile is looked up here, from the view.
        """
        self._manage.open_edit_game(
            self, executable, name,
            self._state.profiles,
            lambda _exec, new_name, _profile:
                self._rename_game(executable, new_name.strip()),
        )

    def _create_game_profile(self, executable: str, name: str, profile: str) -> None:
        """Create the profile a new game belongs to, carrying the game.

        ADD GAME creates both: in LinGHub a game is owned by a profile, so a
        game with no profile left matches nothing. A profile name that is
        already in use is refused by the daemon and reported, not silently
        attached to the existing one.
        """
        profile = profile.strip()
        if profile in self._state.profiles:
            self._status.set_text(
                f"Profile {profile!r} already exists; "
                "rename it or choose another name."
            )
            return
        run_and_report(
            self._do_create_game_profile(executable, name, profile),
            self._on_async_error,
        )

    async def _do_create_game_profile(
        self, executable: str, name: str, profile: str
    ) -> None:
        async def change() -> bool:
            ok = await self._client.create_profile(profile, executable)
            if not ok:
                return False
            if name and name != executable:
                return await self._client.rename_game(profile, executable, name)
            return True

        await self._writes.run(
            change,
            report=self._status.set_text,
            failure="Could not add the game",
            rejected=(
                f"Cannot add {executable!r}. The profile name may be in use."
            ),
            success=f"Added {name or executable} to {profile}.",
        )

    def _rename_game(self, executable: str, name: str) -> None:
        """Set a game's display name, reporting on the status line.

        The prompt has closed by the time the daemon answers, so its errors
        belong on the status line rather than in a dialog nobody is looking
        at.
        """
        profile = self._profile_of_game(executable)
        if profile is None:
            self._status.set_text(f"No profile carries {executable}.")
            return

        async def change() -> bool:
            return await self._client.rename_game(profile, executable, name)

        async def do():
            await self._writes.run(
                change,
                report=self._status.set_text,
                failure="Could not rename the game",
                rejected=f"Cannot rename {executable!r}.",
                success=f"Renamed the game to {name}.",
            )

        run_and_report(do(), self._on_async_error)

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
            self._confirm_switch(name, load=False)
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
        self._refresh()

    def _prompt_duplicate_profile(self, name: str) -> None:
        self._ask_for_text(
            title=f"Duplicate {name}",
            label="New profile name",
            initial=f"{name} copy",
            on_accept=lambda new, _exec, dialog: run_and_report(
                self._do_duplicate_profile(name, new.strip(), dialog),
                self._on_async_error,
            ),
        )

    async def _do_duplicate_profile(self, old: str, new: str, dialog) -> None:
        if not new:
            dialog.show_error("Enter a name for the copy.")
            return

        async def change() -> bool:
            return await self._client.duplicate_profile(old, new)

        await self._writes.run(
            change,
            report=dialog.show_error,
            failure="Could not duplicate the profile",
            rejected=f"Cannot name the copy {new!r}. The name may be in use.",
            success=f"Copied {old} to {new}.",
            on_success=dialog.close,
        )

    def _prompt_canvas_delete(self, name: str) -> None:
        if name == self._state.desktop_profile:
            self._status.set_text("The desktop profile cannot be deleted.")
            return
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=f"Delete {name}?",
            body="Its bindings, DPI and lighting settings are lost, "
                 "along with its games.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect(
            "response",
            lambda _d, response: (
                run_and_report(self._do_delete_profile(name), self._on_async_error)
                if response == "delete"
                else None
            ),
        )
        dialog.present()

    def _confirm_switch_for_canvas(self) -> None:
        """Ask what to do with unsaved changes before opening the canvas."""
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Unsaved changes",
            body=(
                f"Apply your changes to {self._editing} before managing "
                "profiles?"
            ),
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
                return
            if response == "discard":
                self._pending.clear()
                self._sync_save_buttons()
                self._show_canvas()
                return
            if response == "save":
                run_and_report(
                    self._save_then_open_canvas(), self._on_async_error
                )

        dialog.connect("response", on_response)
        dialog.present()

    async def _save_then_open_canvas(self) -> None:
        """Save the pending edits, then open the canvas only on success."""
        profile = self._editing_profile()
        if profile is None:
            return
        await self._do_save(profile)
        if self._pending.dirty:
            # The save was refused; the edits stay where they are.
            return
        self._show_canvas()

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
        self._refresh()
        # Through the injected scheduler, like the refresh: a test drives its
        # own loop, and the GTK bridge would never run there.
        self._schedule(self._load_profile(name), self._on_async_error)

    def _confirm_switch(self, name: str, *, load: bool = True) -> None:
        """Ask what to do with unsaved changes before switching profiles.

        `load=False` is the canvas's DETAILS action: the destination is
        "editing the profile", not "editing and loading it", so accept paths
        that would put it on the mouse are not offered.
        """
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Unsaved changes",
            body=(
                f"Apply your changes to {self._editing} before "
                f"switching to {name}?"
                if load
                else f"Apply your changes to {self._editing} before "
                f"editing {name}?"
            ),
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
                # Put the list back on the profile still being edited.
                self._reselect_current()
                return
            if response == "discard":
                if load:
                    self._apply_selection(name)
                else:
                    self._edit_without_loading(name)
                return
            if response == "save":
                run_and_report(
                    self._save_then_select(name, load=load),
                    self._on_async_error,
                )

        dialog.connect("response", on_response)
        dialog.present()

    async def _save_then_select(self, name: str, *, load: bool = True) -> None:
        """Save the pending edits, then switch only if the save succeeded."""
        profile = self._editing_profile()
        if profile is None:
            return
        await self._do_save(profile)
        if self._pending.dirty:
            # The save was refused; stay where the edits are.
            self._reselect_current()
            return
        if load:
            self._apply_selection(name)
        else:
            self._edit_without_loading(name)

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
