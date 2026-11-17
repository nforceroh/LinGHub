"""Get at the daemon from a synchronous context.

The window runs on the GLib loop and can await a client directly, but the tray
runs a GTK3 main loop that is not an asyncio loop at all, and `linghub status`
has no loop whatsoever. Both used to build a client, connect, do one thing and
disconnect, each with its own `asyncio.run` and its own thread.

This module owns that lifecycle once. Callers say what they want to do; the
module handles connecting, running it on a fresh event loop, and disconnecting.

Deliberately not a client wrapper: it takes a callable so it cannot grow an
interface that mirrors DaemonClient's.

The import of DaemonState at module level is safe for the tray: it pulls in
dbus_fast but no GTK namespace, so GTK3 and GTK4 still never meet.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Callable, TypeVar

from .ui.client import DaemonState


logger = logging.getLogger("linghub.daemon_access")


T = TypeVar("T")


class DaemonUnavailable(RuntimeError):
    """The daemon is not running, or is not answering on the session bus."""


async def run_with_client(action: Callable[[Any], T]) -> T:
    """Connect to the daemon, run `action(client)`, then disconnect.

    Raises DaemonUnavailable when there is no daemon, so callers can tell
    "nothing there" from "the call failed".
    """
    from .ui.client import DaemonClient

    client = DaemonClient()
    if not await client.connect():
        raise DaemonUnavailable("cannot reach the session bus")
    try:
        return await action(client)
    finally:
        # Whatever the action does, the connection is not left open. Errors
        # from the action propagate unchanged: a bug inside it is not a
        # missing daemon, and reporting it as one hides the bug.
        client.disconnect()


def call(action: Callable[[Any], T], timeout: float = 10.0) -> T:
    """Run `action(client)` from synchronous code on a fresh event loop.

    One loop per call rather than a shared one: these calls are short, and a
    shared loop would need pumping from whatever main loop the caller has,
    which is the thing this module exists to avoid.
    """
    return asyncio.run(asyncio.wait_for(run_with_client(action), timeout))


def state() -> DaemonState:
    """The daemon's current state. Convenience for the common case."""
    async def read(client):
        return await client.state()

    return call(read)


class Watcher:
    """A long-lived connection that reports when the daemon changes.

    The tray cannot await a client: its GTK3 loop is not an asyncio loop. But
    it can keep one connection open on a thread with its own loop, and be told
    when something happens instead of asking every two seconds.

    `on_change` is called from that thread, so a GTK caller must hand off to
    the main loop itself (the tray uses GLib.idle_add).
    """

    def __init__(self, on_change: Callable[[], None]):
        self._on_change = on_change
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        """Connect and begin watching, on a thread of its own."""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Ask the watch loop to finish and close its connection.

        Only the event is set: the loop polls it, so it exits its own way and
        the connection closes in the `finally`. Stopping the loop directly
        would abort `run_until_complete` mid-await and raise.
        """
        self._stop.set()

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._watch())
        except Exception:  # noqa: BLE001 - a tray must not die on a bad watch
            logger.exception("daemon watch failed")
        finally:
            loop.close()

    async def _watch(self) -> None:
        """Hold the connection open until stopped.

        The connection is what makes the subscription work: the client's
        message handler fires on this loop, so the loop must keep running.
        """
        from .ui.client import DaemonClient

        client = DaemonClient()
        if not await client.connect():
            logger.debug("daemon unavailable; the tray will poll instead")
            return
        client.set_change_handler(self._on_change)
        try:
            while not self._stop.is_set():
                await asyncio.sleep(0.2)
        finally:
            client.disconnect()
