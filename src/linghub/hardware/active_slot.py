"""Decide the active slot: the mouse's answer, with ratbagd's as a fallback.

The rules from #2 (ADR-0010):

- The mouse wins. When ratbagd believes otherwise, that is logged once for
  as long as the disagreement lasts.
- A node that is gone (OSError) is a lost mouse: it propagates, and the
  daemon reconnects.
- A mouse that is silent or answers with an error leaves the slot unknown:
  SlotUnknown, which is neither drift nor a lost mouse.
- A node the user may not open (another session has the seat) falls back to
  ratbagd's answer, with one warning until access comes back.
- Host mode leaves the slot unknown, with one warning.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Awaitable, Callable, Protocol

from . import hidpp
from .failures import MouseAbsent, SlotUnknown

logger = logging.getLogger(__name__)


class MouseSlot(Protocol):
    def active_slot(self) -> int: ...


class ActiveSlotReader:
    """Reads the active slot once per check, applying the rules above."""

    def __init__(
        self,
        believed: Callable[[], Awaitable[int | None]],
        mouse: MouseSlot | None,
    ):
        """`believed` is ratbagd's answer; `mouse` is None when the node
        behind the device could not be confirmed, leaving only ratbagd."""
        self._believed = believed
        self._mouse = mouse
        self._disagreement: tuple[int | None, int] | None = None
        self._refused = False
        self._host_mode = False

    async def read(self) -> int | None:
        believed = await self._believed()
        if self._mouse is None:
            return believed

        try:
            # Off the event loop: a silent mouse costs a timeout, and the
            # daemon's D-Bus interface must keep answering meanwhile.
            actual = await asyncio.to_thread(self._mouse.active_slot)
        except PermissionError as exc:
            if not self._refused:
                logger.warning(
                    "permission to read the mouse was refused (%s); "
                    "using ratbagd's answer until it comes back", exc,
                )
                self._refused = True
            return believed
        except hidpp.HostMode:
            if not self._host_mode:
                logger.warning(
                    "the mouse is in host mode, so no slot is active; "
                    "another tool may have taken it over"
                )
                self._host_mode = True
            raise SlotUnknown("the mouse is in host mode") from None
        except (hidpp.NoReply, hidpp.HidppError) as exc:
            logger.debug("the mouse did not say which slot it is on: %s", exc)
            raise SlotUnknown(str(exc)) from exc

        self._refused = False
        self._host_mode = False
        if believed != actual:
            if self._disagreement != (believed, actual):
                logger.info("ratbagd says slot %s, the mouse says slot %s", believed, actual)
                self._disagreement = (believed, actual)
        else:
            self._disagreement = None
        return actual


def mouse_for(
    device_path: str,
    sys_root: Path = Path("/sys/class/hidraw"),
    open_node: Callable[[Path], hidpp.Transport] = hidpp.HidrawTransport,
) -> hidpp.OnboardProfiles | None:
    """A reader for the mouse behind a confirmed ratbagd device, or None.

    None when the node exists but cannot be confirmed as a Logitech device:
    reading it could read another device, so the daemon falls back to
    ratbagd's answer for this connection and says so once, loudly.

    Raises MouseAbsent when the node is already gone, so connecting fails
    as it would for any missing mouse.
    """
    try:
        node = hidpp.node_for(device_path, sys_root=sys_root)
    except hidpp.NodeGone as exc:
        # ratbagd still lists a mouse the kernel has removed: the mouse is
        # still missing, so this connection fails and the absence goes on.
        from .ratbag import NOT_FOUND

        raise MouseAbsent(NOT_FOUND) from exc
    except hidpp.NodeMismatch as exc:
        logger.error(
            "cannot read the active slot from the mouse: %s; using ratbagd's answer", exc
        )
        return None
    return hidpp.OnboardProfiles(lambda: open_node(node))
