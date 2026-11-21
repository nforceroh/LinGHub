"""The one rule every window write obeys: run, report, refresh.

The window has seven write sites. Before this module each restated the
ordering and set its own status string; the two helpers they shared differed
only in where the failure text went. These tests pin the rule itself, so a
call site cannot get the ordering wrong.
"""

import unittest

from linghub.ui.daemon_write import DaemonWrite


class Recorder:
    """Collects what a write reported, in order."""

    def __init__(self):
        self.messages: list[str] = []
        self.refreshed = 0
        self.settled = 0

    def report(self, message: str) -> None:
        self.messages.append(message)

    async def refresh(self) -> None:
        self.refreshed += 1

    def settle(self) -> None:
        self.settled += 1


def accepted():
    async def change() -> bool:
        return True

    return change


def refused():
    async def change() -> bool:
        return False

    return change


def failing(exc: Exception):
    async def change() -> bool:
        raise exc

    return change


class AcceptedTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.recorder = Recorder()
        self.writes = DaemonWrite(self.recorder.refresh)

    async def test_a_success_message_is_reported(self):
        ok = await self.writes.run(
            accepted(), report=self.recorder.report,
            failure="Could not do it", success="Did it.",
        )
        self.assertTrue(ok)
        self.assertEqual(self.recorder.messages, ["Did it."])

    async def test_the_view_is_refreshed_once(self):
        await self.writes.run(
            accepted(), report=self.recorder.report, failure="Could not do it"
        )
        self.assertEqual(self.recorder.refreshed, 1)

    async def test_no_success_message_means_nothing_is_reported(self):
        await self.writes.run(
            accepted(), report=self.recorder.report, failure="Could not do it"
        )
        self.assertEqual(self.recorder.messages, [])

    async def test_on_success_runs_before_the_refresh(self):
        """A panel must accept its values as the baseline before the read
        that will show them, or the refresh sees a dirty panel."""
        order = []

        async def refresh():
            order.append("refresh")

        writes = DaemonWrite(refresh)
        await writes.run(
            accepted(), report=self.recorder.report,
            failure="Could not do it",
            on_success=lambda: order.append("settle"),
        )
        self.assertEqual(order, ["settle", "refresh"])

    async def test_a_constructor_on_success_is_the_default(self):
        writes = DaemonWrite(self.recorder.refresh, on_success=self.recorder.settle)
        await writes.run(
            accepted(), report=self.recorder.report, failure="Could not do it"
        )
        self.assertEqual(self.recorder.settled, 1)

    async def test_a_per_call_on_success_wins(self):
        writes = DaemonWrite(self.recorder.refresh, on_success=self.recorder.settle)
        await writes.run(
            accepted(), report=self.recorder.report,
            failure="Could not do it", on_success=lambda: None,
        )
        self.assertEqual(self.recorder.settled, 0)


class RefusedTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.recorder = Recorder()
        self.writes = DaemonWrite(self.recorder.refresh)

    async def test_a_refusal_is_not_refreshed(self):
        """Nothing changed, so there is nothing new to read."""
        ok = await self.writes.run(
            refused(), report=self.recorder.report, failure="Could not do it"
        )
        self.assertFalse(ok)
        self.assertEqual(self.recorder.refreshed, 0)

    async def test_a_refusal_is_silent_without_a_rejected_message(self):
        """The change itself already reported why it was refused."""
        await self.writes.run(
            refused(), report=self.recorder.report, failure="Could not do it"
        )
        self.assertEqual(self.recorder.messages, [])

    async def test_a_rejected_message_is_reported(self):
        await self.writes.run(
            refused(), report=self.recorder.report,
            failure="Could not do it", rejected="That name is taken.",
        )
        self.assertEqual(self.recorder.messages, ["That name is taken."])

    async def test_a_refusal_does_not_settle(self):
        await self.writes.run(
            refused(), report=self.recorder.report,
            failure="Could not do it", on_success=self.recorder.settle,
        )
        self.assertEqual(self.recorder.settled, 0)


class TransportErrorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.recorder = Recorder()
        self.writes = DaemonWrite(self.recorder.refresh)

    async def test_a_transport_error_names_what_was_attempted(self):
        ok = await self.writes.run(
            failing(RuntimeError("the daemon is gone")),
            report=self.recorder.report, failure="Could not change the DPI",
        )
        self.assertFalse(ok)
        self.assertEqual(
            self.recorder.messages,
            ["Could not change the DPI: the daemon is gone"],
        )

    async def test_an_os_error_is_a_transport_error_too(self):
        await self.writes.run(
            failing(OSError("no bus")),
            report=self.recorder.report, failure="Could not load",
        )
        self.assertEqual(self.recorder.messages, ["Could not load: no bus"])

    async def test_a_transport_error_is_not_refreshed(self):
        await self.writes.run(
            failing(RuntimeError("gone")),
            report=self.recorder.report, failure="Could not do it",
        )
        self.assertEqual(self.recorder.refreshed, 0)

    async def test_an_unexpected_error_propagates(self):
        """A bug is not a write failure: it must reach the caller's handler."""
        with self.assertRaises(ValueError):
            await self.writes.run(
                failing(ValueError("a bug")),
                report=self.recorder.report, failure="Could not do it",
            )


if __name__ == "__main__":
    unittest.main()
