"""A tray icon for LinGHub.

This is a separate process, and deliberately so: AppIndicator3 is GTK3 and GTK3
cannot be loaded in the same process as the GTK4 UI - `gi` refuses to load two
versions of the Gtk namespace. Keeping the tray in its own module also means it
survives closing the main window, which is the point of a tray icon.

It reads state from the daemon over D-Bus and asks the daemon to switch
profiles; it never touches the config or the hardware itself.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AppIndicator3", "0.1")

from gi.repository import AppIndicator3, GLib, Gtk


logger = logging.getLogger("linghub.tray")

INDICATOR_ID = "linghub"
ICON_NAME = "input-mouse"


class Tray:
    """The indicator, its menu, and the polling that keeps it current."""

    def __init__(self):
        self._indicator = AppIndicator3.Indicator.new(
            INDICATOR_ID, ICON_NAME, AppIndicator3.IndicatorCategory.HARDWARE
        )
        self._indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)

        self._menu = Gtk.Menu()
        self._status_item = Gtk.MenuItem(label="Connecting…")
        self._status_item.set_sensitive(False)
        self._menu.append(self._status_item)
        self._menu.append(Gtk.SeparatorMenuItem())

        self._profile_items: list[Gtk.MenuItem] = []
        self._profiles_box = Gtk.MenuItem(label="Load profile")
        self._profiles_menu = Gtk.Menu()
        self._profiles_box.set_submenu(self._profiles_menu)
        self._menu.append(self._profiles_box)
        self._menu.append(Gtk.SeparatorMenuItem())

        open_item = Gtk.MenuItem(label="Open LinGHub")
        open_item.connect("activate", lambda _w: self._open_ui())
        self._menu.append(open_item)

        quit_item = Gtk.MenuItem(label="Quit tray")
        quit_item.connect("activate", lambda _w: Gtk.main_quit())
        self._menu.append(quit_item)

        self._menu.show_all()
        self._indicator.set_menu(self._menu)
        self._indicator.set_title("LinGHub")

        self._state = None
        self._busy = False

    def start(self) -> None:
        """Begin polling the daemon, then run the GTK main loop."""
        GLib.timeout_add_seconds(2, self._refresh)
        GLib.timeout_add_seconds(1, self._refresh)
        Gtk.main()

    # --- daemon access ---------------------------------------------------

    def _refresh(self) -> bool:
        """Poll the daemon in a thread, so the menu never blocks."""
        if self._busy:
            return GLib.SOURCE_CONTINUE
        self._busy = True
        threading.Thread(target=self._refresh_thread, daemon=True).start()
        return GLib.SOURCE_CONTINUE

    def _refresh_thread(self) -> None:
        import asyncio

        try:
            state = asyncio.run(self._query())
        finally:
            self._busy = False
        if state is not None:
            GLib.idle_add(self._apply, state)

    async def _query(self):
        from .ui.client import DaemonClient

        client = DaemonClient()
        if not await client.connect():
            return None
        try:
            return await client.state()
        except (RuntimeError, OSError):
            return None
        finally:
            client.disconnect()

    def _apply(self, state) -> bool:
        """Update the menu from a daemon state snapshot."""
        changed = self._state is None or state.active_profile != self._state.active_profile
        self._state = state

        if state.detected_game:
            self._status_item.set_label(f"Playing {state.detected_game}")
        else:
            self._status_item.set_label(
                f"Active: {state.active_profile or 'unknown'}"
            )
        self._indicator.set_label("", "")

        names = tuple(state.profiles)
        current = tuple(item.get_label() for item in self._profile_items)
        if names != current:
            self._rebuild_profiles(names)

        for item in self._profile_items:
            item.set_sensitive(item.get_label() != state.active_profile)

        if changed:
            self._indicator.set_title(
                f"LinGHub — {state.active_profile or 'unknown'}"
            )
        return GLib.SOURCE_REMOVE

    def _rebuild_profiles(self, names: tuple[str, ...]) -> None:
        for item in self._profile_items:
            self._profiles_menu.remove(item)
        self._profile_items = []
        for name in names:
            item = Gtk.MenuItem(label=name)
            item.connect("activate", lambda _w, n=name: self._load(n))
            self._profiles_menu.append(item)
            self._profile_items.append(item)
        self._profiles_menu.show_all()
        self._profiles_box.set_sensitive(bool(names))

    # --- actions ---------------------------------------------------------

    def _report_failure(self, message: str) -> None:
        """Tell the user something failed, since a tray has no console.

        A silent failure is indistinguishable from a menu item that does
        nothing, which is exactly how this looked before.
        """
        try:
            dialog = Gtk.MessageDialog(
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.CLOSE,
                text=message,
            )
            dialog.set_title("LinGHub")
            dialog.run()
            dialog.destroy()
        except Exception:  # noqa: BLE001 - a dialog must never crash the tray
            logger.error("%s", message)

    def _load(self, name: str) -> None:
        """Ask the daemon to load a profile, in the background."""
        threading.Thread(target=self._load_thread, args=(name,), daemon=True).start()

    def _load_thread(self, name: str) -> None:
        import asyncio

        async def run():
            from .ui.client import DaemonClient

            client = DaemonClient()
            if not await client.connect():
                return
            try:
                await client.load_profile(name)
            except (RuntimeError, OSError) as exc:
                logger.warning("could not load %r: %s", name, exc)
            finally:
                client.disconnect()

        asyncio.run(run())
        GLib.idle_add(self._refresh)

    def _open_ui(self) -> None:
        """Launch the UI as its own process.

        Not a fork: the UI is GTK4 and this process is GTK3, so they cannot
        share an address space.

        The interpreter is used rather than a `linghub` command, because the
        console script is only on PATH when the virtualenv is active - which it
        is not for a systemd unit. sys.executable is the interpreter already
        running this tray, so it is guaranteed to be able to import linghub.
        """
        command = [sys.executable, "-m", "linghub.cli", "ui"]
        try:
            subprocess.Popen(
                command, start_new_session=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            logger.error("could not open the UI: %s", exc)
            self._report_failure(f"Could not open LinGHub: {exc}")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not Gtk.init_check(sys.argv[:1]):
        print("Error: cannot open a display for the tray icon.", file=sys.stderr)
        return 1
    Tray().start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
