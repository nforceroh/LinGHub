"""Client for the daemon's D-Bus interface.

The UI never edits the config file directly: the daemon is the single writer,
so every change goes through here.
"""

from __future__ import annotations

import asyncio
import logging

from dbus_fast import BusType, Message, MessageType, Variant
from dbus_fast.aio import MessageBus


from .. import dbus_contract as contract
from .. import version
from ..daemon_view import (
    DaemonUnavailable,
    DaemonView,
    ProfileSummary,
    ProfileView,
    ViewState,
)


SERVICE = contract.SERVICE
PATH = contract.PATH
INTERFACE = contract.INTERFACE

logger = logging.getLogger("linghub.ui.client")

# A daemon's answers when it has no such property: dbus-fast says
# UnknownProperty, GLib-based services say InvalidArgs.
_NO_PROPERTY = frozenset({
    "org.freedesktop.DBus.Error.UnknownProperty",
    "org.freedesktop.DBus.Error.InvalidArgs",
})

# The bus's answers when nothing owns the daemon's name. Connecting to the bus
# succeeds without the daemon, so these replies are the only sign it is absent.
_NO_DAEMON = frozenset({
    "org.freedesktop.DBus.Error.ServiceUnknown",
    "org.freedesktop.DBus.Error.NameHasNoOwner",
})


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
        # The daemon's own signals, and its name gaining or losing an owner:
        # with no poll, the second is how a client notices the daemon started
        # or stopped.
        rules = (
            f"type='signal',interface='{INTERFACE}'",
            "type='signal',interface='org.freedesktop.DBus',"
            f"member='NameOwnerChanged',arg0='{SERVICE}'",
        )
        try:
            for rule in rules:
                await self._bus.call(Message(
                    destination="org.freedesktop.DBus",
                    path="/org/freedesktop/DBus",
                    interface="org.freedesktop.DBus",
                    member="AddMatch",
                    signature="s",
                    body=[rule],
                ))
        except (OSError, asyncio.TimeoutError):
            return False
        return True

    def set_change_handler(self, handler) -> None:
        self._on_change = handler

    def _handle_signal(self, message: Message) -> None:
        if message.message_type != MessageType.SIGNAL:
            return
        ours = message.interface == INTERFACE
        daemon_came_or_went = (
            message.member == "NameOwnerChanged"
            and bool(message.body) and message.body[0] == SERVICE
        )
        if not (ours or daemon_came_or_went):
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
        # GetView now returns two structs, and a decoder that kept only the
        # first would silently drop the other. The tuple is the whole body.
        if reply.body and len(reply.body) > 1:
            return tuple(reply.body)
        return reply.body[0] if reply.body else None

    async def get_view(self, profile: str) -> DaemonView:
        """Read the state and one profile's editable sections, in one call.

        An unknown profile comes back with empty sections rather than an
        error: the window may be reading a profile that was just deleted, and
        "nothing there" is the answer it needs.
        """
        raw = await self._invoke(contract.GET_VIEW, profile)
        # Two shapes reach this decoder. A daemon from before the canvas
        # answers with one flat struct of nine fields and no summaries; the
        # current one answers with the state+sections struct and a second
        # summaries struct. Accepting both means an old daemon costs the
        # canvas its tiles rather than the window its state.
        if len(raw) == 2 and not isinstance(raw[0], str):
            main, summaries = raw
        else:
            main, summaries = raw, ()
        (
            active, detected, desktop, names,
            bindings, leds, resolutions, rates, rate,
        ) = main
        return DaemonView(
            state=ViewState(
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
            summaries=tuple(
                ProfileSummary(
                    name=str(name),
                    dpi=int(dpi),
                    report_rate=int(rate_value),
                    games=tuple(
                        (str(executable), str(game_name))
                        for executable, game_name in games
                    ),
                )
                for name, dpi, rate_value, games in summaries
            ),
        )

    async def daemon_version(self) -> version.DaemonVersion:
        """What the daemon is running, as one value (ADR-0009).

        A property of its own rather than part of GetView, so a daemon from
        before version reporting answers "no such property" here and every
        other read still works. The mapping from what the bus says to what
        the user is told happens here, once, so the CLI, the tray and the
        window cannot each decide it differently.
        """
        if self._bus is None:
            return version.DaemonVersion.not_running()
        try:
            reply = await asyncio.wait_for(
                self._bus.call(Message(
                    destination=SERVICE, path=PATH,
                    interface="org.freedesktop.DBus.Properties", member="Get",
                    signature="ss", body=[INTERFACE, contract.VERSION.name],
                )),
                timeout=5,
            )
        except (OSError, TimeoutError):
            return version.DaemonVersion.unreadable()
        if reply.message_type == MessageType.ERROR:
            if reply.error_name in _NO_PROPERTY:
                return version.DaemonVersion.predates_reporting()
            if reply.error_name in _NO_DAEMON:
                return version.DaemonVersion.not_running()
            return version.DaemonVersion.unreadable()
        value = reply.body[0]
        return version.DaemonVersion.known(
            str(value.value if isinstance(value, Variant) else value)
        )

    async def load_profile(self, name: str) -> bool:
        return bool(await self._invoke(contract.LOAD_PROFILE, name))

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

    async def duplicate_profile(self, name: str, new: str) -> bool:
        return bool(await self._invoke(contract.DUPLICATE_PROFILE, name, new))

    async def rename_game(self, profile: str, executable: str, name: str) -> bool:
        return bool(await self._invoke(contract.RENAME_GAME, profile, executable, name))

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
