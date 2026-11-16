"""The LinGHub main window.

Shows the mouse diagram, the profile list, and the bindings of the selected
profile. Clicking a button in the table opens the binding editor; the change
goes to the daemon over D-Bus, which is the only writer of the config
(ADR-0004).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk

from .asyncbridge import run_and_report
from .binding_editor import BindingEditor
from .binding_labels import describe_binding
from .buttonmap import BUTTONS, describe, manual_number
from .client import DaemonClient, DaemonState
from .diagram import MouseDiagram
from .dpi_panel import DpiPanel
from .led_panel import LedPanel


logger = logging.getLogger("linghub.ui.window")

IMAGE = Path(__file__).resolve().parents[3] / "images" / "g502_trans.png"


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, application, client: DaemonClient):
        super().__init__(application=application, title="LinGHub")
        self._client = client
        self._state = DaemonState()
        self._selected_button: int | None = None
        self._bindings: dict[int, tuple[str, str]] = {}
        self._profile_rows: dict[str, Adw.ActionRow] = {}
        self._led_panel: LedPanel | None = None
        self._dpi_panel: DpiPanel | None = None
        self._leds: dict[int, dict] = {}
        self._resolutions: list[dict] = []
        self._report_rates: tuple[int, ...] = ()
        self._report_rate: int = 0

        self.set_default_size(980, 620)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="LinGHub", subtitle=""))
        self._title = header.get_title_widget()
        toolbar.add_top_bar(header)

        self._status = Gtk.Label(label="Connecting…")
        self._status.add_css_class("dim-label")
        self._status.set_margin_top(6)
        self._status.set_margin_bottom(6)
        toolbar.add_top_bar(self._status)

        toolbar.set_content(self._build_content())
        self.set_content(toolbar)

        client.set_change_handler(self._on_daemon_change)
        GLib.timeout_add_seconds(2, self._poll)

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

        top.append(self._section_label("Profiles"))
        self._profile_list = Gtk.ListBox()
        self._profile_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._profile_list.connect("row-activated", self._on_profile_activated)
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

    def _poll(self) -> bool:
        run_and_report(self._refresh(), self._on_async_error)
        return GLib.SOURCE_CONTINUE

    def _on_daemon_change(self) -> None:
        GLib.idle_add(self._refresh_from_idle)

    def _refresh_from_idle(self) -> bool:
        run_and_report(self._refresh(), self._on_async_error)
        return GLib.SOURCE_REMOVE

    def _on_async_error(self, exc: Exception) -> None:
        self._status.set_text(f"Error: {exc}")

    async def _refresh(self) -> None:
        try:
            state = await self._client.state()
        except (RuntimeError, OSError) as exc:
            self._status.set_text(f"Daemon unavailable: {exc}")
            return
        await self._refresh_bindings()
        self._apply_state(state)

    def _apply_state(self, state: DaemonState) -> None:
        self._state = state

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
            # Never reload the panel over unsaved edits: the poll runs every
            # two seconds and would silently discard whatever the user is in
            # the middle of choosing.
            if not self._led_panel.dirty:
                self._led_panel.load(self._leds)
        if self._dpi_panel is not None and not self._dpi_panel.dirty:
            self._dpi_panel.load(
                self._resolutions, self._report_rates, self._report_rate
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
        try:
            for index, (dpi, is_default, disabled) in enumerate(slots):
                ok = await self._client.set_resolution(
                    profile, index, dpi,
                    make_default=is_default, disabled=disabled,
                )
                if not ok:
                    self._status.set_text(f"The daemon rejected DPI slot {index + 1}.")
                    return
            if rate and not await self._client.set_report_rate(profile, rate):
                self._status.set_text("The daemon rejected that report rate.")
                return
        except (RuntimeError, OSError) as exc:
            self._status.set_text(f"Could not change the DPI: {exc}")
            return
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
        try:
            ok = await self._client.set_leds(profile, mode, brightness, duration, color)
        except (RuntimeError, OSError) as exc:
            self._status.set_text(f"Could not change the lighting: {exc}")
            return
        if not ok:
            self._status.set_text("The daemon rejected that lighting change.")
            return
        # Only now do the panel's values become the saved baseline, so a
        # failed write leaves the edits intact and still worth retrying.
        if self._led_panel is not None:
            self._led_panel.mark_saved()
        self._status.set_text(f"Updated the lighting of {profile}.")

    async def _refresh_bindings(self) -> None:
        """Read the edited profile's bindings and lighting."""
        profile = self._editing_profile()
        if profile is None:
            self._bindings = {}
            self._leds = {}
            return
        try:
            self._bindings = await self._client.get_bindings(profile)
        except (RuntimeError, OSError) as exc:
            logger.warning("cannot read bindings: %s", exc)
            self._bindings = {}
        try:
            self._leds = await self._client.get_leds(profile)
        except (RuntimeError, OSError) as exc:
            logger.warning("cannot read lighting: %s", exc)
            self._leds = {}
        try:
            self._resolutions = await self._client.get_resolutions(profile)
            self._report_rates = await self._client.get_report_rates(profile)
            self._report_rate = await self._client.get_report_rate(profile)
        except (RuntimeError, OSError) as exc:
            logger.warning("cannot read DPI: %s", exc)
            self._resolutions = []

    def _rebuild_profiles(self) -> None:
        """Make the profile list match the daemon's state, reusing rows.

        Rows are updated in place rather than recreated. Rebuilding the list
        on every two-second poll destroyed the user's selection, so clicking a
        profile appeared to bounce back to the first row.
        """
        names = self._state.profiles

        # Drop rows for profiles that went away.
        existing = self._profile_rows
        for name in [name for name in existing if name not in names]:
            self._profile_list.remove(existing.pop(name))

        for position, name in enumerate(names):
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

            is_active = name == self._state.active_profile
            row._check.set_visible(is_active)
            row.set_subtitle("active" if is_active else "")
            row._desktop.set_visible(name == self._state.desktop_profile)

    def _rebuild_bindings(self) -> None:
        """Fill in what each button does, and highlight the selected row."""
        for index, widget in self._table_rows.items():
            if index == self._selected_button:
                widget.add_css_class("accent")
            else:
                widget.remove_css_class("accent")

            kind, value = self._bindings.get(index, ("", None))
            label = self._binding_rows.get(index)
            if label is not None:
                label.set_text(describe_binding(kind, value) if kind else "—")

    def _apply_bindings(self, bindings: dict[int, tuple[str, str]]) -> None:
        self._bindings = dict(bindings)
        self._rebuild_bindings()

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
        """The profile edits apply to: the active one, else the desktop one."""
        return (
            self._state.active_profile
            or self._state.desktop_profile
            or (self._state.profiles[0] if self._state.profiles else None)
        )

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
        try:
            if kind == "disabled":
                ok = await self._client.clear_binding(profile, index)
            else:
                ok = await self._client.set_binding(profile, index, kind, str(value))
        except (RuntimeError, OSError) as exc:
            self._status.set_text(f"Could not change the binding: {exc}")
            return
        if not ok:
            self._status.set_text("The daemon rejected that binding.")
            return
        self._status.set_text(f"Updated {describe(index)} in {profile}.")
        await self._refresh()

    # --- interaction -----------------------------------------------------

    def _on_button_selected(self, _diagram, index: int) -> None:
        self._selected_button = index
        if self._diagram is not None:
            self._diagram.set_selected(index)
        self._button_detail.set_text(f"Selected: {describe(index)}")
        self._rebuild_bindings()

    def _on_profile_activated(self, _list, row) -> None:
        name = row.get_title()
        run_and_report(self._load_profile(name), self._on_async_error)

    async def _load_profile(self, name: str) -> None:
        try:
            ok = await self._client.load_profile(name)
        except (RuntimeError, OSError) as exc:
            self._status.set_text(f"Could not load {name}: {exc}")
            return
        if not ok:
            self._status.set_text(f"Daemon rejected profile {name}")
            return
        await self._refresh()
