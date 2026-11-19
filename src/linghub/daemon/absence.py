"""One absence of the mouse, and what to say about it (#4, #12).

A KVM switch can leave the mouse on another machine for minutes. The rules
that keep the log quiet and accurate while it is away are real behaviour, so
they live here rather than in three `Daemon` fields changed by three methods
with slightly different rules:

- The first failed search of an absence is logged; every later one is debug.
- A mouse that comes back is announced with how long it was away.
- A mouse missing at startup is not "back": there was nothing to come back
  from, and the connector's own "found ..." line already says so.

The clock is injected, so the rules are tested directly instead of by
counting log lines through `tick()`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Report:
    """What to log about one event.

    `level` is the level for the first report of an absence; later ones are
    debug. A method returns None instead of a Report when there is nothing
    to say.
    """

    message: str
    level: int = logging.WARNING


class Absence:
    """The mouse's absence: when it started, and what has been said about it.

    The daemon reports what happened and logs what comes back. It keeps no
    absence state of its own.
    """

    def __init__(self, clock: Callable[[], float]):
        self._clock = clock
        self._since: float | None = None
        self._reported = False
        self._ever_connected = False

    @property
    def ongoing(self) -> bool:
        """Whether the mouse is away right now."""
        return self._since is not None

    def lost(self, message: str) -> Report:
        """The mouse went away while we had it: start the clock, say so.

        This line is the event that starts the absence, not one of the
        once-per-absence search reports, so it is always said. Losing it
        also means we had it, so coming back is worth a "back" line.
        """
        self._ever_connected = True
        self._start()
        return Report(message, logging.WARNING)

    def search_failed(self, message: str, level: int = logging.WARNING) -> Report:
        """A search found nothing: start the clock if needed, warn once.

        `level` is for the first report only; a misconfiguration is an error,
        a missing mouse a warning.
        """
        self._start()
        return self._first(message, level)

    def found(self) -> Report | None:
        """The mouse is back: say how long it was away, unless it never left.

        A mouse missing at startup has no "back" line: the connector's own
        "found ..." line is the first thing the user sees, and "back after
        0s" would be noise. None means there is nothing to say.
        """
        if self._since is None:
            self._ever_connected = True
            return None
        away = _duration(self._clock() - self._since)
        first = not self._ever_connected
        self._since = None
        self._reported = False
        self._ever_connected = True
        if first:
            return None
        return Report(f"device is back after {away}", logging.INFO)

    def _start(self) -> None:
        if self._since is None:
            self._since = self._clock()
            self._reported = False

    def _first(self, message: str, level: int) -> Report:
        if self._reported:
            return Report(message, logging.DEBUG)
        self._reported = True
        return Report(message, level)


def _duration(seconds: float) -> str:
    """A short human duration: 45s, 3m 12s, 1h 2m."""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"
