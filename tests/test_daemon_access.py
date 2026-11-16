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

    async def test_disconnects_after_a_failure(self):
        async def action(client):
            raise RuntimeError("boom")

        with self.assertRaises(daemon_access.DaemonUnavailable):
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

    async def test_a_runtime_error_becomes_daemon_unavailable(self):
        """Callers should not have to know about D-Bus exception types."""
        async def action(client):
            raise OSError("no bus")

        with self.assertRaises(daemon_access.DaemonUnavailable):
            await daemon_access.run_with_client(action)


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


if __name__ == "__main__":
    unittest.main()
