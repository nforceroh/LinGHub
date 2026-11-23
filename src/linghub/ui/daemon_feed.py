"""What the window knows about the daemon, and what it tells the user.

The window's version story has two halves, and both live here. One is the
banner: when other code is running, the window must say so, and quietly
accept the case where it cannot tell (an old predates it; a stopped daemon
does not count as a mismatch). The other is the About dialog, which reports
both sides of that comparison every time the user opens it.

The widgets to speak through are injected, so the module is testable with no
display. It owns no window state beyond the daemon's version, which is the
state this module is about.
"""

from __future__ import annotations

import logging

from .. import version

logger = logging.getLogger("linghub.ui.daemon_feed")


class DaemonFeed:
    """Watching for the daemon's version, and telling the user about it."""

    def __init__(self, *, client, schedule, report, wanted_profile,
                 apply_view, current_version, banner):
        # The client and the scheduler arrive as they do on the window, so a
        # test can drive both with its own loop.
        # The client arrives as a zero-argument callable, so a test can swap
        # the window's client after this module was constructed.
        self._client = client
        self._schedule = schedule
        self._report = report
        self._wanted_profile = wanted_profile
        self._apply_view = apply_view
        self._current = current_version
        self._banner = banner
        self._daemon_version = version.DaemonVersion.not_running()
        self._refresh_task = None
        self._refresh_pending = False

    @property
    def daemon_version(self):
        return self._daemon_version

    def apply_daemon_version(self, daemon_version) -> None:
        """Remember the daemon's version, and flag it if it differs from ours."""
        self._daemon_version = daemon_version
        _line, note = version.describe(self._current, daemon_version)
        self._banner.set_title(note or "")
        self._banner.set_revealed(note is not None)

    def about_comments(self):
        """This app's version, with the daemon's beside it."""
        line, note = version.describe(self._current, self._daemon_version)
        return line if note is None else f"{line}\n{note}"

    def _report_error(self, exc: Exception) -> None:
        self._report(f"Error: {exc}")

    # --- reading ----------------------------------------------------------

    def refresh(self) -> None:
        """Read the daemon once, coalescing requests that arrive mid-flight.

        Three triggers call this: opening the window or connecting, the
        daemon's change signals, and every successful write. A read already
        in flight means this request collapses into one repeat when it
        finishes, so a slow read cannot land after a newer one.
        """
        if self._refresh_task is not None and not self._refresh_task.done():
            self._refresh_pending = True
            return
        self._refresh_task = self._schedule(self._refresh_loop(), self._report_error)

    async def refresh_now(self) -> None:
        """Refresh and wait for it, for callers whose message must survive.

        A write reports its outcome on the status line, and applying a view
        overwrites that line. The write path therefore has to let the refresh
        finish before it reports, or the user never sees the message.
        """
        self.refresh()
        if self._refresh_task is not None:
            await self._refresh_task

    async def _refresh_loop(self) -> None:
        while True:
            await self._read_and_apply()
            if not self._refresh_pending:
                return
            self._refresh_pending = False

    async def _read_and_apply(self) -> None:
        wanted = self._wanted_profile() or ""
        try:
            view = await self._client().get_view(wanted)
        except (RuntimeError, OSError) as exc:
            self._report(f"Daemon unavailable: {exc}")
            self.apply_daemon_version(version.DaemonVersion.not_running())
            return
        self._apply_view(view)
        # The first read has no state yet, so it cannot name a profile and asks
        # for "". That answer carries the profile list but no profile's
        # sections, so the panels would stay empty until something else
        # happened to trigger a read. Now that the state is known, read again
        # for the profile we should actually be editing.
        if not wanted and self._wanted_profile():
            self._refresh_pending = True
        # Read after the view, and on its own: a failure here must not cost
        # the user the state they came to see.
        try:
            daemon_version = await self._client().daemon_version()
        except (RuntimeError, OSError) as exc:
            logger.debug("cannot read the daemon's version: %s", exc)
            daemon_version = version.DaemonVersion.unreadable()
        self.apply_daemon_version(daemon_version)
