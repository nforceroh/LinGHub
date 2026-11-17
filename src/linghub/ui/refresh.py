"""One refresh at a time, with the last request winning.

The window refreshes from three places: the two-second poll, the daemon's
change signals, and after every successful write. Nothing stopped two of them
from running at once, so a slow read could land after a newer one and show a
stale view.

The rule is small and pure: while a refresh is in flight, further requests
collapse into a single pending flag; when the running one finishes it repeats
once if anything asked. That is all the coordination the window needs, and it
is testable without a GTK loop.
"""

from __future__ import annotations


class RefreshGuard:
    """Serialise refreshes, coalescing requests that arrive mid-flight."""

    def __init__(self) -> None:
        self._running = False
        self._pending = False

    @property
    def running(self) -> bool:
        return self._running

    def begin(self) -> bool:
        """Claim the refresh slot.

        True means the caller should do the work. False means one is already
        running; the request is remembered and the running refresh repeats.
        """
        if self._running:
            self._pending = True
            return False
        self._running = True
        return True

    def end(self) -> bool:
        """Release the slot. True means a request arrived while running."""
        self._running = False
        pending, self._pending = self._pending, False
        return pending
