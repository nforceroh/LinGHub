"""The daemon's caller for the retrigger helper (#19).

Every failure is a logged False, never an exception: the daemon's retry loop
keeps looking either way, and the misconfigured message already tells the
user the manual fix.
"""

import unittest
from unittest import mock

from linghub.hardware import retrigger


class FakeBus:
    """Records the call, answers what the test says."""

    def __init__(self, reply=None, error=None):
        self.sent = None
        self._reply = reply
        self._error = error
        self.disconnected = False

    async def connect(self):
        return self

    def disconnect(self):
        self.disconnected = True

    async def call(self, message):
        self.sent = message
        if self._error is not None:
            raise self._error
        return self._reply


class FakeReply:
    """Just what nudge reads: the type and the body."""

    def __init__(self, message_type, body):
        self.message_type = message_type
        self.body = body


def _reply(body=None):
    from dbus_fast import MessageType

    return FakeReply(MessageType.METHOD_RETURN, body or [True])


class NudgeTests(unittest.TestCase):
    def test_a_successful_nudge_sends_the_node_and_says_so(self):
        bus = FakeBus(reply=_reply())
        self.assertTrue(asyncio_ok(retrigger.nudge("hidraw5", connect_bus=bus)))
        self.assertEqual(bus.sent.destination, retrigger.BUS_NAME)
        self.assertEqual(bus.sent.body, ["hidraw5"])
        self.assertTrue(bus.disconnected, "the connection is dropped after one nudge")

    def test_a_refusal_is_logged_and_answered_false(self):
        from dbus_fast import Message, MessageType

        from dbus_fast import MessageType

        refused = FakeReply(MessageType.ERROR, ["nope"])
        bus = FakeBus(reply=refused)
        with self.assertLogs("linghub.hardware.retrigger", "WARNING"):
            self.assertFalse(asyncio_ok(retrigger.nudge("hidraw5", connect_bus=bus)))

    def test_a_missing_helper_is_logged_and_answered_false(self):
        bus = FakeBus(error=ConnectionRefusedError("no such bus name"))
        with self.assertLogs("linghub.hardware.retrigger", "WARNING"):
            self.assertFalse(asyncio_ok(retrigger.nudge("hidraw5", connect_bus=bus)))
        self.assertTrue(bus.disconnected, "even a failed call drops the connection")


def asyncio_ok(coro):
    import asyncio

    return asyncio.run(coro)


if __name__ == "__main__":
    unittest.main()
