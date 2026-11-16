"""Observe Feral GameMode's game registrations.

GameMode is an optional accelerator, not a requirement. It fires only for
games launched through `gamemoderun` or with `libgamemodeauto` preloaded, so
the daemon must keep working when it is absent, not running, or silent.

The signals live on the session bus, unlike ratbagd which is on the system
bus.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from dbus_fast import BusType, Message, MessageType
from dbus_fast.aio import MessageBus


SERVICE = "com.feralinteractive.GameMode"
PATH = "/com/feralinteractive/GameMode"
INTERFACE = "com.feralinteractive.GameMode"

logger = logging.getLogger("linghub.gamemode")


@dataclass(frozen=True)
class RegisteredGame:
    pid: int
    path: str


class GameModeClient:
    """Subscribe to GameMode's registration signals.

    `on_change` is called whenever a game registers or unregisters, so the
    daemon can run a detection pass immediately instead of waiting for the
    next poll.
    """

    def __init__(self, on_change):
        self._on_change = on_change
        self._bus: MessageBus | None = None
        self._available = False

    @property
    def available(self) -> bool:
        return self._available

    async def connect(self) -> bool:
        """Attach to the session bus and subscribe. Returns False if absent."""
        try:
            self._bus = await asyncio.wait_for(
                MessageBus(bus_type=BusType.SESSION).connect(), timeout=5
            )
        except (OSError, asyncio.TimeoutError) as exc:
            logger.info("GameMode unavailable: %s", exc)
            return False

        self._bus.add_message_handler(self._handle_message)

        try:
            reply = await asyncio.wait_for(
                self._bus.call(Message(
                    destination="org.freedesktop.DBus",
                    path="/org/freedesktop/DBus",
                    interface="org.freedesktop.DBus",
                    member="AddMatch",
                    signature="s",
                    body=[f"type='signal',interface='{INTERFACE}'"],
                )),
                timeout=5,
            )
        except (OSError, asyncio.TimeoutError) as exc:
            logger.info("GameMode unavailable: %s", exc)
            return False

        if reply.message_type == MessageType.ERROR:
            logger.info("GameMode unavailable: %s", reply.body)
            return False

        # AddMatch only registers a rule with the bus daemon, so it succeeds
        # even when gamemoded is not running. Probe the service itself to
        # report availability honestly.
        self._available = await self._probe()
        if self._available:
            logger.info("subscribed to GameMode signals")
        else:
            logger.info("GameMode signals subscribed, but gamemoded is not running")
        return True

    async def _probe(self) -> bool:
        """True if gamemoded currently owns its bus name.

        Uses NameHasOwner rather than calling a GameMode method: any method
        call would D-Bus-activate gamemoded, so the act of checking would
        start it and the check could never report "not running".
        """
        if self._bus is None:
            return False
        try:
            reply = await asyncio.wait_for(
                self._bus.call(Message(
                    destination="org.freedesktop.DBus",
                    path="/org/freedesktop/DBus",
                    interface="org.freedesktop.DBus",
                    member="NameHasOwner",
                    signature="s",
                    body=[SERVICE],
                )),
                timeout=2,
            )
        except (OSError, asyncio.TimeoutError):
            return False
        if reply.message_type == MessageType.ERROR:
            return False
        return bool(reply.body[0])

    def _handle_message(self, message: Message) -> None:
        if message.message_type != MessageType.SIGNAL:
            return
        if message.interface != INTERFACE:
            return
        if message.member not in ("GameRegistered", "GameUnregistered"):
            return

        pid, path = message.body
        logger.info("GameMode %s: pid %s", message.member, pid)
        self._on_change()

    async def list_games(self) -> list[RegisteredGame]:
        """Games already registered, for catching one that started earlier."""
        if self._bus is None:
            return []
        try:
            reply = await asyncio.wait_for(
                self._bus.call(Message(
                    destination=SERVICE,
                    path=PATH,
                    interface=INTERFACE,
                    member="ListGames",
                )),
                timeout=5,
            )
        except (OSError, asyncio.TimeoutError):
            return []

        if reply.message_type == MessageType.ERROR:
            return []
        return [RegisteredGame(pid=pid, path=path) for pid, path in reply.body[0]]

    def disconnect(self) -> None:
        if self._bus is not None:
            self._bus.disconnect()
            self._bus = None
        self._available = False
