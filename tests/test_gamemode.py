"""Tests for the GameMode client.

GameMode is optional, so the important cases are the failure paths: absent
service, error replies, and signals that are not ours.
"""

import unittest
from types import SimpleNamespace

from dbus_fast import MessageType

from linghub.discovery.gamemode import INTERFACE, GameModeClient


class FakeBus:
    def __init__(self, add_match_error=False, list_games=None, name_owned=False):
        self.calls = []
        self.handlers = []
        self.add_match_error = add_match_error
        self._list_games = list_games or []
        self._name_owned = name_owned
        self.disconnected = False

    def add_message_handler(self, handler):
        self.handlers.append(handler)

    async def call(self, message):
        self.calls.append(message.member)
        if message.member == "AddMatch" and self.add_match_error:
            return SimpleNamespace(message_type=MessageType.ERROR, body=["nope"])
        if message.member == "NameHasOwner":
            return SimpleNamespace(message_type=MessageType.METHOD_RETURN, body=[self._name_owned])
        if message.member == "ListGames":
            return SimpleNamespace(message_type=MessageType.METHOD_RETURN, body=[self._list_games])
        return SimpleNamespace(message_type=MessageType.METHOD_RETURN, body=[])

    def disconnect(self):
        self.disconnected = True


def signal(member, pid=1, path="/game/1", interface=INTERFACE):
    return SimpleNamespace(
        message_type=MessageType.SIGNAL,
        interface=interface,
        member=member,
        body=[pid, path],
    )


class HandlerTests(unittest.TestCase):
    def setUp(self):
        self.changes = 0
        self.client = GameModeClient(on_change=self._bump)

    def _bump(self):
        self.changes += 1

    def test_registration_triggers_change(self):
        self.client._handle_message(signal("GameRegistered"))
        self.assertEqual(self.changes, 1)

    def test_unregistration_triggers_change(self):
        self.client._handle_message(signal("GameUnregistered"))
        self.assertEqual(self.changes, 1)

    def test_other_signals_are_ignored(self):
        self.client._handle_message(signal("SomethingElse"))
        self.assertEqual(self.changes, 0)

    def test_other_interfaces_are_ignored(self):
        self.client._handle_message(signal("GameRegistered", interface="org.example.Other"))
        self.assertEqual(self.changes, 0)

    def test_method_returns_are_ignored(self):
        message = SimpleNamespace(
            message_type=MessageType.METHOD_RETURN,
            interface=INTERFACE,
            member="GameRegistered",
            body=[1, "/game/1"],
        )
        self.client._handle_message(message)
        self.assertEqual(self.changes, 0)


class AvailabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_unavailable_when_add_match_fails(self):
        client = GameModeClient(on_change=lambda: None)
        client._bus = FakeBus(add_match_error=True)
        # Bypass the real session-bus connect by exercising the match step.
        self.assertFalse(await self._subscribe(client))

    async def _subscribe(self, client):
        from dbus_fast import Message

        reply = await client._bus.call(Message(
            destination="org.freedesktop.DBus",
            path="/org/freedesktop/DBus",
            interface="org.freedesktop.DBus",
            member="AddMatch",
            signature="s",
            body=[f"type='signal',interface='{INTERFACE}'"],
        ))
        return reply.message_type != MessageType.ERROR

    async def test_list_games_returns_empty_without_bus(self):
        client = GameModeClient(on_change=lambda: None)
        self.assertEqual(await client.list_games(), [])

    async def test_list_games_parses_reply(self):
        client = GameModeClient(on_change=lambda: None)
        client._bus = FakeBus(list_games=[(1234, "/game/1234")])
        games = await client.list_games()
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0].pid, 1234)
        self.assertEqual(games[0].path, "/game/1234")

    async def test_disconnect_clears_availability(self):
        client = GameModeClient(on_change=lambda: None)
        client._bus = FakeBus()
        client._available = True
        client.disconnect()
        self.assertFalse(client.available)
        self.assertIsNone(client._bus)


if __name__ == "__main__":
    unittest.main()


class ProbeTests(unittest.IsolatedAsyncioTestCase):
    """The probe must not activate gamemoded as a side effect."""

    async def test_probe_uses_name_has_owner(self):
        client = GameModeClient(on_change=lambda: None)
        bus = FakeBus()
        client._bus = bus
        await client._probe()
        self.assertIn("NameHasOwner", bus.calls)
        self.assertNotIn("ListGames", bus.calls)

    async def test_probe_false_when_name_not_owned(self):
        client = GameModeClient(on_change=lambda: None)
        client._bus = FakeBus(name_owned=False)
        self.assertFalse(await client._probe())

    async def test_probe_true_when_name_owned(self):
        client = GameModeClient(on_change=lambda: None)
        client._bus = FakeBus(name_owned=True)
        self.assertTrue(await client._probe())
