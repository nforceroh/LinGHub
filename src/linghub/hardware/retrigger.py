"""Nudge udev about a node ratbagd missed, through the root helper.

The helper (`linghub-retrigger`, a D-Bus-activated system service) re-presents
one hidraw node to udev, which is the only cure for a ratbagd that enumerated
before the mouse finished initializing (#19). This module is the daemon's
caller: one method, one node name, and a log line for every way it can fail.
A refused or missing helper is not an error the daemon surfaces — the
MouseMisconfigured message already tells the user the manual fix.
"""

from __future__ import annotations

import logging

from dbus_fast import BusType, Message, MessageType
from dbus_fast.aio import MessageBus

logger = logging.getLogger(__name__)

BUS_NAME = "org.linghub.Retrigger"
OBJECT_PATH = "/org/linghub/Retrigger"
INTERFACE = "org.linghub.Retrigger"
TIMEOUT = 10.0


async def nudge(node: str, *, connect_bus=None) -> bool:
    """Ask the helper to re-present `node`. True when it said it did.

    The connection is made per nudge and dropped after: a nudge is rare, and
    owning no bus keeps this module independent of the connector's lifecycle.
    `connect_bus` is injected so a test can hand the call a fake bus. Every
    failure is logged and answered False: the daemon's retry loop keeps
    looking either way, and the misconfigured message already carries the
    manual fix for a helper that is missing or refused.
    """
    try:
        if connect_bus is not None:
            bus = await connect_bus.connect()
        else:
            bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        try:
            reply = await bus.call(
                Message(
                    destination=BUS_NAME,
                    path=OBJECT_PATH,
                    interface=INTERFACE,
                    member="Retrigger",
                    body=[node],
                )
            )
        finally:
            bus.disconnect()
    except Exception as exc:
        logger.warning("cannot nudge udev about %s: %s", node, exc)
        return False
    if reply.message_type != MessageType.METHOD_RETURN:
        logger.warning("the retrigger helper refused %s: %s", node, reply.body)
        return False
    logger.info("nudged udev about %s; ratbagd should pick the mouse up", node)
    return True
