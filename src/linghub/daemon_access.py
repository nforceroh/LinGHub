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
