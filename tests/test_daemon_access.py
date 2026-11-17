"""Tests for the shared daemon-access module.

The important behaviours are that a missing daemon is reported as its own
error rather than a generic failure, and that the client is always
disconnected - a leaked session-bus connection would accumulate.
"""

import unittest

from linghub import daemon_access


class FakeClient:
    instances: list = []

    def __init__(self):
        self.connected = False
        self.disconnected = False
        self.fail_connect = False
        FakeClient.instances.append(self)

    async def connect(self):
        if self.fail_connect:
            return False
        self.connected = True
        return True

    async def state(self):
        return "state"

    def set_change_handler(self, handler):
        self._on_change = handler

    def disconnect(self):
        self.disconnected = True


class RunWithClientTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        FakeClient.instances = []
        # Inject the fake by replacing the import target.
        import linghub.ui.client as real_client
        self._real = real_client.DaemonClient
        real_client.DaemonClient = FakeClient

    def tearDown(self):
        import linghub.ui.client as real_client
        real_client.DaemonClient = self._real

    async def test_runs_the_action_and_returns_its_result(self):
        async def action(client):
            return await client.state()

        self.assertEqual(await daemon_access.run_with_client(action), "state")

    async def test_disconnects_after_success(self):
        async def action(client):
            return None

        await daemon_access.run_with_client(action)
        self.assertTrue(FakeClient.instances[-1].disconnected)

    async def test_a_missing_daemon_raises_daemon_unavailable(self):
        async def make_failing():
            return None

        # Force the next client to fail to connect.
        original_init = FakeClient.__init__

        def failing_init(self):
            original_init(self)
            self.fail_connect = True

        FakeClient.__init__ = failing_init
        try:
            with self.assertRaises(daemon_access.DaemonUnavailable):
                await daemon_access.run_with_client(lambda c: None)
        finally:
            FakeClient.__init__ = original_init

    async def test_an_action_error_propagates_unchanged(self):
        """A bug inside the action is not a missing daemon.

        The module exists to tell those two apart, so collapsing them defeats
        its purpose: a real bug would be reported as "no daemon".
        """
        async def action(client):
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError) as caught:
            await daemon_access.run_with_client(action)
        self.assertNotIsInstance(caught.exception, daemon_access.DaemonUnavailable)

    async def test_an_os_error_from_the_action_propagates(self):
        async def action(client):
            raise OSError("disk on fire")

        with self.assertRaises(OSError):
            await daemon_access.run_with_client(action)

    async def test_the_client_is_still_disconnected_when_the_action_raises(self):
        async def action(client):
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            await daemon_access.run_with_client(action)
        self.assertTrue(FakeClient.instances[-1].disconnected)


class CallTests(unittest.TestCase):
    def setUp(self):
        FakeClient.instances = []
        import linghub.ui.client as real_client
        self._real = real_client.DaemonClient
        real_client.DaemonClient = FakeClient

    def tearDown(self):
        import linghub.ui.client as real_client
        real_client.DaemonClient = self._real

    def test_call_works_from_synchronous_code(self):
        async def action(client):
            return "done"

        self.assertEqual(daemon_access.call(action), "done")

    def test_state_is_a_convenience_for_the_common_case(self):
        self.assertEqual(daemon_access.state(), "state")


class WatcherTests(unittest.TestCase):
    """The tray's long-lived subscription.

    The watcher owns a connection on its own thread and reports changes; the
    GTK caller hops to the main loop itself. These tests pin the lifecycle
    without a bus: connect, register the handler, disconnect on stop.
    """

    def setUp(self):
        FakeClient.instances = []
        import linghub.ui.client as real_client
        self._real = real_client.DaemonClient
        real_client.DaemonClient = FakeClient

    def tearDown(self):
        import linghub.ui.client as real_client
        real_client.DaemonClient = self._real

    def test_the_handler_is_registered_on_the_client(self):
        import asyncio

        calls = []
        watcher = daemon_access.Watcher(lambda: calls.append(1))
        watcher._stop.set()  # return from the loop immediately
        asyncio.run(watcher._watch())
        client = FakeClient.instances[-1]
        self.assertIsNotNone(client._on_change)
        client._on_change()
        self.assertEqual(calls, [1])

    def test_a_missing_daemon_does_not_raise(self):
        """The tray falls back to its slow poll rather than dying."""
        import asyncio

        original_init = FakeClient.__init__

        def failing_init(self):
            original_init(self)
            self.fail_connect = True

        FakeClient.__init__ = failing_init
        try:
            watcher = daemon_access.Watcher(lambda: None)
            asyncio.run(watcher._watch())  # must not raise
        finally:
            FakeClient.__init__ = original_init

    def test_stopping_disconnects(self):
        import asyncio

        watcher = daemon_access.Watcher(lambda: None)
        watcher._stop.set()
        asyncio.run(watcher._watch())
        self.assertTrue(FakeClient.instances[-1].disconnected)


if __name__ == "__main__":
    unittest.main()
