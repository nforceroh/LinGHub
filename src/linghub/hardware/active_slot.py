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
import enum
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol, assert_never

from . import hidpp
from .failures import SlotUnknown

logger = logging.getLogger(__name__)


class MouseSlot(Protocol):
    def active_slot(self) -> int: ...


class Reason(enum.Enum):
    """Why the mouse could not say which slot it is on."""

    UNCONFIRMED_NODE = "unconfirmed node"
    NO_PERMISSION = "no permission"
    HOST_MODE = "host mode"
    NO_ANSWER = "no answer"


@dataclass(frozen=True)
class NoReading:
    """The mouse could not say which slot it is on, and why."""

    reason: Reason
    detail: str = ""


@dataclass(frozen=True)
class SlotReadings:
    """What each source said about the active slot, without a verdict.

    `answer` is the mouse's slot, or a NoReading saying why it couldn't say.
    `believed` is ratbagd's answer, None if it believes no slot is active.
    """

    answer: int | NoReading
    believed: int | None


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

    @property
    def can_read(self) -> bool:
        """True when there is a mouse to ask.

        A caller deciding whether to ask at all needs this one answer; how
        the reader stores the mouse is the reader's business.
        """
        return self._mouse is not None

    async def readings(self) -> SlotReadings:
        """Both answers, and why the mouse couldn't give one, if it couldn't.

        Decides nothing and logs nothing: `read` applies the daemon's rules
        on top, and `linghub status` shows both answers as they are (#5).
        A gone node still raises OSError: that is a lost mouse, not a reading.
        """
        believed = await self._believed()
        if self._mouse is None:
            return SlotReadings(NoReading(Reason.UNCONFIRMED_NODE), believed)
        try:
            # Off the event loop: a silent mouse costs a timeout, and the
            # daemon's D-Bus interface must keep answering meanwhile.
            actual = await asyncio.to_thread(self._mouse.active_slot)
        except PermissionError as exc:
            return SlotReadings(NoReading(Reason.NO_PERMISSION, str(exc)), believed)
        except hidpp.HostMode as exc:
            return SlotReadings(NoReading(Reason.HOST_MODE, str(exc)), believed)
        except (hidpp.NoReply, hidpp.HidppError) as exc:
            return SlotReadings(NoReading(Reason.NO_ANSWER, str(exc)), believed)
        return SlotReadings(actual, believed)

    async def read(self) -> int | None:
        """The active slot by the daemon's rules, logging each change once."""
        readings = await self.readings()

        if isinstance(readings.answer, NoReading):
            return self._without_an_answer(readings)

        self._refused = False
        self._host_mode = False
        believed, actual = readings.believed, readings.answer
        if believed != actual:
            if self._disagreement != (believed, actual):
                logger.info("ratbagd says slot %s, the mouse says slot %s", believed, actual)
                self._disagreement = (believed, actual)
        else:
            self._disagreement = None
        return actual

    def _without_an_answer(self, readings: SlotReadings) -> int | None:
        """The daemon's verdict when the mouse could not say, logging once."""
        no_reading, believed = readings.answer, readings.believed
        match no_reading.reason:
            case Reason.UNCONFIRMED_NODE:
                return believed
            case Reason.NO_PERMISSION:
                if not self._refused:
                    logger.warning(
                        "permission to read the mouse was refused (%s); "
                        "using ratbagd's answer until it comes back", no_reading.detail,
                    )
                    self._refused = True
                return believed
            case Reason.HOST_MODE:
                if not self._host_mode:
                    logger.warning(
                        "the mouse is in host mode, so no slot is active; "
                        "another tool may have taken it over"
                    )
                    self._host_mode = True
                raise SlotUnknown("the mouse is in host mode")
            case Reason.NO_ANSWER:
                logger.debug("the mouse did not say which slot it is on: %s", no_reading.detail)
                raise SlotUnknown(no_reading.detail)
            case _:
                assert_never(no_reading.reason)
