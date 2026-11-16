"""The LinGHub main window.

Shows the mouse diagram, the profile list, and the bindings of the selected
profile. Editing is not wired up yet: this milestone is read-only plus manual
profile switching, so the UI can be verified against the daemon before adding
write paths.
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
from .buttonmap import BUTTONS, describe
from .client import DaemonClient, DaemonState
from .diagram import MouseDiagram


logger = logging.getLogger("linghub.ui.window")

IMAGE = Path(__file__).resolve().parents[3] / "images" / "g502.png"


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, application, client: DaemonClient):
        super().__init__(application=application, title="LinGHub")
        self._client = client
        self._state = DaemonState()
        self._selected_button: int | None = None

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
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)

        box.append(self._section_label("Profiles"))
        self._profile_list = Gtk.ListBox()
        self._profile_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._profile_list.connect("row-activated", self._on_profile_activated)
        scroller = Gtk.ScrolledWindow()
        scroller.set_child(self._profile_list)
        scroller.set_vexpand(True)
        scroller.set_min_content_height(160)
        box.append(scroller)

        box.append(self._section_label("Bindings"))
        self._binding_list = Gtk.ListBox()
        self._binding_list.set_selection_mode(Gtk.SelectionMode.NONE)
        binding_scroller = Gtk.ScrolledWindow()
        binding_scroller.set_child(self._binding_list)
        binding_scroller.set_vexpand(True)
        box.append(binding_scroller)

        return box

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

    def _rebuild_profiles(self) -> None:
        child = self._profile_list.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._profile_list.remove(child)
            child = nxt

        for name in self._state.profiles:
            row = Adw.ActionRow(title=name)
            if name == self._state.active_profile:
                row.set_subtitle("active")
                row.add_prefix(Gtk.Image.new_from_icon_name("object-select-symbolic"))
            if name == self._state.desktop_profile:
                row.add_suffix(Gtk.Label(label="desktop"))
            row.set_activatable(True)
            self._profile_list.append(row)

    def _rebuild_bindings(self) -> None:
        child = self._binding_list.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._binding_list.remove(child)
            child = nxt

        for spot in BUTTONS:
            row = Adw.ActionRow(title=describe(spot.index))
            row.set_subtitle(f"ratbag index {spot.index}")
            if spot.index == self._selected_button:
                row.add_prefix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            self._binding_list.append(row)

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
