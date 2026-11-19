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

from . import daemon_access, version


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
        quit_item.connect("activate", lambda _w: self._quit())
        self._menu.append(quit_item)
        self._menu.append(Gtk.SeparatorMenuItem())

        # This process's app version, fixed at startup, then a note that
        # appears only when the daemon is running different code.
        self._version_item = Gtk.MenuItem(label=f"LinGHub {version.current()}")
        self._version_item.set_sensitive(False)
        self._menu.append(self._version_item)
        self._daemon_note_item = Gtk.MenuItem(label="")
        self._daemon_note_item.set_sensitive(False)
        self._daemon_note_item.set_no_show_all(True)
        self._menu.append(self._daemon_note_item)

        self._menu.show_all()
        self._indicator.set_menu(self._menu)
        self._indicator.set_title("LinGHub")

        self._state = None
        self._busy = False
        self._watcher: daemon_access.Watcher | None = None

    def start(self) -> None:
        """Watch for daemon changes, then run the GTK main loop.

        The daemon announces every change the tray cares about, so the tray
        subscribes instead of asking every two seconds. The timer stays as a
        slow fallback: a missed signal (a daemon restart, a dropped match)
        must not leave the menu stale forever.
        """
        self._watcher = daemon_access.Watcher(self._on_daemon_change)
        self._watcher.start()
        GLib.timeout_add_seconds(30, self._refresh)
        self._refresh()
        Gtk.main()

    def _on_daemon_change(self) -> None:
        """A signal arrived on the watcher's thread; hop to the GTK loop."""
        GLib.idle_add(self._refresh_once)

    def _quit(self) -> None:
        """Close the subscription before leaving the main loop."""
        if self._watcher is not None:
            self._watcher.stop()
        Gtk.main_quit()

    def _refresh_once(self) -> bool:
        """Read the daemon once, off the GTK loop."""
        self._start_refresh()
        return GLib.SOURCE_REMOVE

    # --- daemon access ---------------------------------------------------

    def _refresh(self) -> bool:
        """The slow fallback poll, in case a signal was missed."""
        self._start_refresh()
        return GLib.SOURCE_CONTINUE

    def _start_refresh(self) -> None:
        """Read the daemon in a thread, unless a read is already running.

        A read already in flight wins: this request is dropped rather than
        queued, because the running read will deliver a fresh snapshot. The
        cost is that a change arriving mid-read waits for the next signal or
        the next fallback tick — up to thirty seconds if the daemon is quiet.
        That is acceptable for a tray menu, and cheaper than a second thread.
        """
        if self._busy:
            return
        self._busy = True
        threading.Thread(target=self._refresh_thread, daemon=True).start()

    def _refresh_thread(self) -> None:
        state = None
        daemon_version = version.DaemonVersion.not_running()
        try:
            state, daemon_version = daemon_access.state_and_version()
        except daemon_access.DaemonUnavailable as exc:
            logger.debug("daemon unavailable: %s", exc)
        except Exception:  # noqa: BLE001 - a tray must not die on a bad poll
            logger.exception("unexpected failure reading daemon state")
            daemon_version = version.DaemonVersion.unreadable()
        finally:
            self._busy = False
        if state is not None:
            GLib.idle_add(self._apply, state)
        GLib.idle_add(self._apply_version, daemon_version)

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

    def _apply_version(self, daemon_version) -> bool:
        """Show a note when the daemon runs code other than this tray's."""
        _line, note = version.describe(version.current(), daemon_version)
        self._daemon_note_item.set_label(note or "")
        self._daemon_note_item.set_visible(note is not None)
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
        # A submenu attached to a MenuItem does not inherit show_all(), so it
        # stays hidden and the parent renders as an empty arrow. Each level has
        # to be shown explicitly.
        for item in self._profile_items:
            item.show()
        self._profiles_menu.show()
        self._profiles_box.show()
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
        async def load(client):
            return await client.load_profile(name)

        try:
            daemon_access.call(load)
        except daemon_access.DaemonUnavailable as exc:
            logger.warning("could not load %r: %s", name, exc)
        except Exception:  # noqa: BLE001 - report, do not kill the tray
            logger.exception("unexpected failure loading %r", name)
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
