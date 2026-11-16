"""Client for the daemon's D-Bus interface.

The UI never edits the config file directly: the daemon is the single writer,
so every change goes through here.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from dbus_fast import BusType, Message, MessageType, Variant
from dbus_fast.aio import MessageBus


SERVICE = "org.linghub.Manager"
PATH = "/org/linghub/Manager"
INTERFACE = "org.linghub.Manager"

logger = logging.getLogger("linghub.ui.client")


@dataclass(frozen=True)
class DaemonState:
    active_profile: str = ""
    detected_game: str = ""
    desktop_profile: str = "desktop"
    profiles: tuple[str, ...] = ()


class DaemonClient:
    """Talk to the running daemon over the session bus."""

    def __init__(self):
        self._bus: MessageBus | None = None
        self._on_change = None

    async def connect(self) -> bool:
        try:
            self._bus = await asyncio.wait_for(
                MessageBus(bus_type=BusType.SESSION).connect(), timeout=5
            )
        except (OSError, asyncio.TimeoutError) as exc:
            logger.warning("cannot reach the session bus: %s", exc)
            return False

        self._bus.add_message_handler(self._handle_signal)
        try:
            await self._bus.call(Message(
                destination="org.freedesktop.DBus",
                path="/org/freedesktop/DBus",
                interface="org.freedesktop.DBus",
                member="AddMatch",
                signature="s",
                body=[f"type='signal',interface='{INTERFACE}'"],
            ))
        except (OSError, asyncio.TimeoutError):
            return False
        return True

    def set_change_handler(self, handler) -> None:
        self._on_change = handler

    def _handle_signal(self, message: Message) -> None:
        if message.message_type != MessageType.SIGNAL:
            return
        if message.interface != INTERFACE:
            return
        if self._on_change is not None:
            self._on_change()

    async def _call(self, member: str, signature: str = "", body=None):
        if self._bus is None:
            raise RuntimeError("not connected to the daemon")
        reply = await asyncio.wait_for(
            self._bus.call(Message(
                destination=SERVICE, path=PATH, interface=INTERFACE,
                member=member, signature=signature, body=body or [],
            )),
            timeout=5,
        )
        if reply.message_type == MessageType.ERROR:
            raise RuntimeError(f"{member} failed: {reply.body}")
        return reply.body[0] if reply.body else None

    async def _property(self, name: str) -> str:
        if self._bus is None:
            raise RuntimeError("not connected to the daemon")
        reply = await asyncio.wait_for(
            self._bus.call(Message(
                destination=SERVICE, path=PATH,
                interface="org.freedesktop.DBus.Properties", member="Get",
                signature="ss", body=[INTERFACE, name],
            )),
            timeout=5,
        )
        if reply.message_type == MessageType.ERROR:
            raise RuntimeError(f"reading {name} failed")
        value = reply.body[0]
        return value.value if isinstance(value, Variant) else ""

    async def state(self) -> DaemonState:
        return DaemonState(
            active_profile=await self._property("ActiveProfile"),
            detected_game=await self._property("DetectedGame"),
            desktop_profile=await self._property("DesktopProfile"),
            profiles=tuple(await self._call("ListProfiles") or ()),
        )

    async def load_profile(self, name: str) -> bool:
        return bool(await self._call("LoadProfile", "s", [name]))

    async def reload(self) -> bool:
        return bool(await self._call("Reload"))

    async def get_bindings(self, profile: str) -> dict[int, tuple[str, str]]:
        """Every binding in a profile, as {button index: (type, value)}."""
        raw = await self._call("GetBindings", "s", [profile]) or ()
        return {
            int(index): (str(kind), str(value))
            for index, kind, value in raw
        }

    async def set_binding(self, profile: str, index: int, kind: str, value: str | None) -> bool:
        return bool(await self._call("SetBinding", "siss", [profile, index, kind, value or ""]))

    async def clear_binding(self, profile: str, index: int) -> bool:
        return bool(await self._call("ClearBinding", "si", [profile, index]))

    async def create_profile(self, name: str, executable: str = "") -> bool:
        return bool(await self._call("CreateProfile", "ss", [name, executable]))

    async def rename_profile(self, old: str, new: str) -> bool:
        return bool(await self._call("RenameProfile", "ss", [old, new]))

    async def delete_profile(self, name: str) -> bool:
        return bool(await self._call("DeleteProfile", "s", [name]))

    async def get_resolutions(self, profile: str) -> list[dict]:
        """A profile's DPI slots in order."""
        raw = await self._call("GetResolutions", "s", [profile]) or ()
        return [
            {
                "index": int(index),
                "dpi": int(dpi),
                "default": bool(is_default),
                "disabled": bool(is_disabled),
            }
            for index, dpi, is_default, is_disabled in raw
        ]

    async def set_resolution(
        self, profile: str, index: int, dpi: int, *,
        make_default: bool = False, disabled: bool = False,
    ) -> bool:
        return bool(await self._call(
            "SetResolution", "siubb",
            [profile, index, dpi, make_default, disabled],
        ))

    async def get_report_rate(self, profile: str) -> int:
        return int(await self._call("GetReportRate", "s", [profile]) or 0)

    async def get_report_rates(self, profile: str) -> tuple[int, ...]:
        return tuple(int(r) for r in await self._call("GetReportRates", "s", [profile]) or ())

    async def set_report_rate(self, profile: str, rate: int) -> bool:
        return bool(await self._call("SetReportRate", "su", [profile, rate]))

    async def get_leds(self, profile: str) -> dict[int, dict]:
        """A profile's LED zones, as {index: {mode, color, brightness, duration}}."""
        raw = await self._call("GetLeds", "s", [profile]) or ()
        return {
            int(index): {
                "mode": str(mode),
                "color": tuple(int(c) for c in color),
                "brightness": int(brightness),
                "duration": int(duration),
            }
            for index, mode, color, brightness, duration in raw
        }

    async def set_leds(
        self,
        profile: str,
        mode: str,
        brightness: int,
        duration: int,
        color: tuple[int, int, int],
    ) -> bool:
        red, green, blue = color
        return bool(await self._call(
            "SetLeds", "ssuuuuu",
            [profile, mode, brightness, duration, red, green, blue],
        ))

    def disconnect(self) -> None:
        if self._bus is not None:
            self._bus.disconnect()
            self._bus = None
