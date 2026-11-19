"""The LinGHub application entry point."""

from __future__ import annotations

import logging
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib

from .. import version
from .asyncbridge import run_and_report
from .client import DaemonClient
from .window import MainWindow


logger = logging.getLogger("linghub.ui")


class LingHubApplication(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id="org.linghub.UI",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self._client = DaemonClient()
        self._window: MainWindow | None = None

    def do_activate(self) -> None:
        if self._window is None:
            self._window = MainWindow(application=self, client=self._client)
        self._window.present()

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        run_and_report(self._connect())

    async def _connect(self) -> None:
        if not await self._client.connect():
            logger.warning("daemon not reachable; the UI will show no state")
            return
        # The window may have been opened, and failed its first read, before
        # the connection was up. Nothing would prompt another read until the
        # daemon next changed, so ask for one now.
        if self._window is not None:
            self._window.refresh()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    # Fix the app version at startup, so it describes the code this process
    # loaded rather than whatever the clone holds when About is opened.
    logger.info("LinGHub %s", version.current())
    app = LingHubApplication()
    # Pass only the program name: GApplication treats extra arguments as files
    # to open, and "ui" is our subcommand, not a file.
    return app.run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
