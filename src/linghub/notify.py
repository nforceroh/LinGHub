"""Desktop notifications, via the freedesktop notification specification.

Plasma, GNOME and most other desktops implement `org.freedesktop.Notifications`
on the session bus, so one implementation covers them. A missing notification
daemon is not an error: the daemon must keep switching profiles on a machine
with no desktop session.
"""

from __future__ import annotations

import logging

from dbus_fast import BusType, Message, Variant
from dbus_fast.aio import MessageBus


SERVICE = "org.freedesktop.Notifications"
PATH = "/org/freedesktop/Notifications"
INTERFACE = "org.freedesktop.Notifications"

APP_NAME = "LinGHub"
ICON = "input-mouse"

logger = logging.getLogger("linghub.notify")


class Notifier:
    """Send notifications, reusing one session-bus connection."""

    def __init__(self, expire_ms: int = 4000):
        self._bus: MessageBus | None = None
        self._expire_ms = expire_ms
        self._replaces: dict[str, int] = {}
        self._available: bool | None = None

    async def connect(self) -> bool:
        """Attach to the session bus and check for a notification server."""
        try:
            self._bus = await MessageBus(bus_type=BusType.SESSION).connect()
        except (OSError, RuntimeError) as exc:
            logger.info("notifications unavailable: %s", exc)
            self._available = False
            return False

        try:
            reply = await self._bus.call(Message(
                destination="org.freedesktop.DBus",
                path="/org/freedesktop/DBus",
                interface="org.freedesktop.DBus",
                member="NameHasOwner",
                signature="s",
                body=[SERVICE],
            ))
            self._available = bool(reply.body[0])
        except (OSError, RuntimeError) as exc:
            logger.info("cannot check for a notification daemon: %s", exc)
            self._available = False

        if not self._available:
            logger.info("no notification daemon; profile switches will be silent")
        return self._available

    @property
    def available(self) -> bool:
        return bool(self._available)

    async def notify(
        self, summary: str, body: str = "", *, tag: str = "", icon: str = ICON
    ) -> bool:
        """Show a notification.

        `tag` makes repeated notifications replace each other, so switching
        profiles twice in a row edits one notification rather than stacking
        two. Returns False when nothing was shown, which is not an error.
        """
        if not self._available or self._bus is None:
            return False

        replaces = self._replaces.get(tag, 0) if tag else 0
        try:
            reply = await self._bus.call(Message(
                destination=SERVICE,
                path=PATH,
                interface=INTERFACE,
                member="Notify",
                signature="susssasa{sv}i",
                body=[
                    APP_NAME,
                    replaces,
                    icon or "",
                    summary,
                    body,
                    [],
                    {"desktop-entry": Variant("s", "linghub")},
                    self._expire_ms,
                ],
            ))
        except (OSError, RuntimeError) as exc:
            logger.warning("could not show a notification: %s", exc)
            return False

        if tag and reply.body:
            self._replaces[tag] = int(reply.body[0])
        return True

    def disconnect(self) -> None:
        if self._bus is not None:
            self._bus.disconnect()
            self._bus = None


def profile_message(profile: str, game: str | None) -> tuple[str, str]:
    """The summary and body for a profile switch.

    Markup is used for the profile name because the notification body supports
    it and a bare name is easy to miss at a glance.
    """
    if game:
        return f"Playing {game}", f"Loaded <b>{profile}</b>"
    return "Back to the desktop", f"Loaded <b>{profile}</b>"


def refused_message(profile: str, reason: str) -> tuple[str, str]:
    """The summary and body for a refused load.

    Worth a notification: the mouse is now on the wrong profile, and without
    one the user finds out in game (#8).
    """
    return f'Couldn\'t load "{profile}"', reason
