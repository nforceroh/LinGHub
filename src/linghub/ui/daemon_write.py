"""One rule for every write the window makes to the daemon.

The window has seven write sites: DPI, lighting, create, rename, delete,
binding, and load. Each runs a coroutine against the daemon, reports the
outcome, and refreshes the view on success. That rule used to be two
near-identical helpers on the window, differing only in where the failure
text went, with each call site setting its own status string afterwards.

This module owns the rule. A call site states what it changes, how to report
a failure, and what to say on success; it does not restate the ordering of
"run, report, refresh".

The reporter is injected rather than assumed because the destination differs:
most writes report on the window's status line, but create and rename run
from a prompt and must show the failure where the user typed. That is the
only thing that varies, so it is the only thing the caller supplies.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable


logger = logging.getLogger("linghub.ui.daemon_write")


# What a write reports a failure with: the status line's set_text, or a
# dialog's show_error. Both take one string.
Reporter = Callable[[str], None]

# A write: returns True when the daemon accepted it, False when it refused.
Change = Callable[[], Awaitable[bool]]


class DaemonWrite:
    """Run a daemon write, report the outcome, and refresh on success.

    Constructed once per window with the client and a way to refresh. The
    refresh is a callable rather than a method call so this module does not
    need to know how the window schedules its reads.
    """

    def __init__(self, refresh: Callable[[], Awaitable[None]]):
        """`refresh` is awaited after a write the daemon accepted."""
        self._refresh = refresh

    async def run(
        self,
        change: Change,
        *,
        report: Reporter,
        failure: str,
        rejected: str | None = None,
        success: str | None = None,
        on_success: Callable[[], None] | None = None,
    ) -> bool:
        """Run `change` and report what happened; True when it was accepted.

        `failure` prefixes a transport error, so the message says what was
        being attempted. `rejected` is the message for a `False` return, when
        the caller has something more specific than `failure` to say; without
        it a refusal is silent, because the change itself already reported a
        reason. `success` is shown on the status line only when the caller
        passes a reporter that writes there. `on_success` runs before the
        refresh, for a caller that has state to settle first — a panel
        accepting its staged values as the new baseline, for instance.
        """
        try:
            ok = await change()
        except (RuntimeError, OSError) as exc:
            report(f"{failure}: {exc}")
            return False

        if not ok:
            if rejected is not None:
                report(rejected)
            return False

        if on_success is not None:
            on_success()
        await self._refresh()
        if success is not None:
            report(success)
        return True
