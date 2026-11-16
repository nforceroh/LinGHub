"""Run asyncio coroutines on the GTK main loop.

GTK's main loop is not an asyncio loop, so `asyncio.ensure_future` fails
inside a GTK callback. This helper drives a dedicated asyncio loop from a
GLib timeout, which is the standard way to combine the two without pulling in
a dependency.
"""

from __future__ import annotations

import asyncio
import logging

from gi.repository import GLib


logger = logging.getLogger("linghub.ui.asyncio")

_loop: asyncio.AbstractEventLoop | None = None


def get_loop() -> asyncio.AbstractEventLoop:
    """The asyncio loop driven by the GTK main loop."""
    global _loop
    if _loop is None:
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
        GLib.timeout_add(10, _pump)
    return _loop


def _pump() -> bool:
    """Run one iteration of the asyncio loop, then reschedule."""
    assert _loop is not None
    try:
        _loop.call_soon(_loop.stop)
        _loop.run_forever()
    except Exception:  # pragma: no cover - defensive
        logger.exception("asyncio pump failed")
    return GLib.SOURCE_CONTINUE


def run(coro) -> asyncio.Task:
    """Schedule a coroutine on the GTK-driven loop."""
    return get_loop().create_task(coro)


def run_and_report(coro, on_error=None) -> asyncio.Task:
    """Schedule a coroutine and surface any exception."""
    task = run(coro)

    def _done(t: asyncio.Task) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.error("async task failed: %s", exc)
            if on_error is not None:
                on_error(exc)

    task.add_done_callback(_done)
    return task
