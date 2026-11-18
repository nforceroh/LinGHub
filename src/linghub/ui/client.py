"""Client for the daemon's D-Bus interface.

The UI never edits the config file directly: the daemon is the single writer,
so every change goes through here.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from dbus_fast import BusType, Message, MessageType, Variant
from dbus_fast.aio import MessageBus


from .. import dbus_contract as contract


SERVICE = contract.SERVICE
PATH = contract.PATH
INTERFACE = contract.INTERFACE

logger = logging.getLogger("linghub.ui.client")

# The bus's answers when nothing owns the daemon's name. Connecting to the bus
# succeeds without the daemon, so these replies are the only sign it is absent.
_NO_DAEMON = frozenset({
    "org.freedesktop.DBus.Error.ServiceUnknown",
    "org.freedesktop.DBus.Error.NameHasNoOwner",
})


class DaemonUnavailable(RuntimeError):
    """The daemon is not running, or is not answering on the session bus."""


@dataclass(frozen=True)
class DaemonState:
    active_profile: str = ""
    detected_game: str = ""
    desktop_profile: str = "desktop"
    profiles: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProfileView:
    """One profile's editable sections, as the window's panels consume them."""

    bindings: dict[int, tuple[str, str]] = field(default_factory=dict)
    leds: dict[int, dict] = field(default_factory=dict)
    resolutions: list[dict] = field(default_factory=list)
    report_rates: tuple[int, ...] = ()
    report_rate: int = 0


@dataclass(frozen=True)
class DaemonView:
    """Everything a poll needs, from one D-Bus read.

    The state section is what the tray and the title bar show; the profile
    section is what the panels edit. One read means a poll cannot piece a
    view together from two ticks.
    """

    state: DaemonState
    profile: ProfileView


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

    async def _invoke(self, member, *args):
        """Call a D-Bus member declared in the contract.

        Going through the contract means the name and signature have one
        owner, and the argument count is checked before anything is sent.
        """
        return await self._call(member.name, member.input, member.call_body(*args))

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
        _raise_for_error(reply, member)
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
        _raise_for_error(reply, f"reading {name}")
        value = reply.body[0]
        return value.value if isinstance(value, Variant) else ""

    async def state(self) -> DaemonState:
        return DaemonState(
            active_profile=await self._property("ActiveProfile"),
            detected_game=await self._property("DetectedGame"),
            desktop_profile=await self._property("DesktopProfile"),
            profiles=tuple(await self._invoke(contract.LIST_PROFILES) or ()),
        )

    async def get_view(self, profile: str) -> DaemonView:
        """Read the state and one profile's editable sections, in one call.

        An unknown profile comes back with empty sections rather than an
        error: the window may be polling a profile that was just deleted, and
        "nothing there" is the answer it needs.
        """
        raw = await self._invoke(contract.GET_VIEW, profile)
        (
            active, detected, desktop, names,
            bindings, leds, resolutions, rates, rate,
        ) = raw
        return DaemonView(
            state=DaemonState(
                active_profile=active,
                detected_game=detected,
                desktop_profile=desktop,
                profiles=tuple(names),
            ),
            profile=ProfileView(
                bindings={
                    int(index): (str(kind), str(value))
                    for index, kind, value in bindings
                },
                leds={
                    int(index): {
                        "mode": str(mode),
                        "color": tuple(int(c) for c in color),
                        "brightness": int(brightness),
                        "duration": int(duration),
                    }
                    for index, mode, color, brightness, duration in leds
                },
                resolutions=[
                    {
                        "index": int(index),
                        "dpi": int(dpi),
                        "default": bool(is_default),
                        "disabled": bool(is_disabled),
                    }
                    for index, dpi, is_default, is_disabled in resolutions
                ],
                report_rates=tuple(int(r) for r in rates),
                report_rate=int(rate),
            ),
        )

    async def load_profile(self, name: str) -> bool:
        return bool(await self._invoke(contract.LOAD_PROFILE, name))

    async def reload(self) -> bool:
        return bool(await self._invoke(contract.RELOAD))

    async def set_binding(self, profile: str, index: int, kind: str, value: str | None) -> bool:
        return bool(await self._invoke(contract.SET_BINDING, profile, index, kind, value or ""))

    async def clear_binding(self, profile: str, index: int) -> bool:
        return bool(await self._invoke(contract.CLEAR_BINDING, profile, index))

    async def create_profile(self, name: str, executable: str = "") -> bool:
        return bool(await self._invoke(contract.CREATE_PROFILE, name, executable))

    async def rename_profile(self, old: str, new: str) -> bool:
        return bool(await self._invoke(contract.RENAME_PROFILE, old, new))

    async def delete_profile(self, name: str) -> bool:
        return bool(await self._invoke(contract.DELETE_PROFILE, name))

    async def set_resolution(
        self, profile: str, index: int, dpi: int, *,
        make_default: bool = False, disabled: bool = False,
    ) -> bool:
        return bool(await self._invoke(
            contract.SET_RESOLUTION, profile, index, dpi, make_default, disabled
        ))

    async def set_report_rate(self, profile: str, rate: int) -> bool:
        return bool(await self._invoke(contract.SET_REPORT_RATE, profile, rate))

    async def set_leds(
        self,
        profile: str,
        mode: str,
        brightness: int,
        duration: int,
        color: tuple[int, int, int],
    ) -> bool:
        red, green, blue = color
        return bool(await self._invoke(
            contract.SET_LEDS, profile, mode, brightness, duration, red, green, blue
        ))

    def disconnect(self) -> None:
        if self._bus is not None:
            self._bus.disconnect()
            self._bus = None


def _raise_for_error(reply: Message, what: str) -> None:
    """Raise if `reply` is an error: DaemonUnavailable when the daemon is absent.

    Any other error is a failure of the call itself, and keeps the bus's
    error name so the caller can see what went wrong.
    """
    if reply.message_type != MessageType.ERROR:
        return
    detail = reply.body[0] if reply.body else ""
    if reply.error_name in _NO_DAEMON:
        raise DaemonUnavailable(f"the daemon is not on the session bus ({detail})")
    raise RuntimeError(f"{what} failed: {reply.error_name}: {detail}")
