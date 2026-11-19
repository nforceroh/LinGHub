"""Ask the mouse which slot it is on, over HID++ 2.0 (#2, ADR-0010).

ratbagd answers "which profile is active" from what it has cached, and was
wrong three times in one day: once saying slot 1 while the mouse sat on 0,
and twice saying the disabled slot 2 after a KVM switch. This module asks the
mouse itself, using the onboard profiles feature (0x8100). It only reads:
writes still go through ratbagd.

The hidraw node is shared. ratbagd (software id 0x8) and the kernel (0x1)
send requests on it too, and every reader sees every reply, so a reply is
ours only if it carries our software id and answers the request we sent.

The node is opened for each read and closed straight after. A KVM switch
deletes it, and a file descriptor kept open on a deleted node is exactly
the stale-holder problem `diagnose` warns about.
"""

from __future__ import annotations

import os
import re
import select
import time
from pathlib import Path
from typing import Callable, Protocol

# Ours, distinct from libratbag's 0x8 and the kernel's 0x1.
SOFTWARE_ID = 0x0A

ONBOARD_PROFILES = 0x8100
WIRED = 0xFF        # a mouse on its own USB cable answers at the node's own address
RECEIVER = 0x01     # a mouse paired to a receiver is device 1 behind it

_SHORT, _LONG = 0x10, 0x11
_HIDPP10_ERROR = 0x8F
_HIDPP20_ERROR = 0xFF

_ROOT = 0x00
_GET_FEATURE = 0
_GET_ONBOARD_MODE = 2
_GET_CURRENT_PROFILE = 4
_HOST_MODE = 2

_NODE_NAME = re.compile(r"^hidraw\d+$")
_LOGITECH = "0000046D"


class NoReply(Exception):
    """The mouse did not answer in time: asleep, out of range, or busy.

    Not a RuntimeError or OSError, which the daemon reads as a lost mouse.
    """


class HidppError(Exception):
    """The mouse, or the receiver in front of it, answered with an error."""


class HostMode(Exception):
    """The mouse is in host mode, so no stored slot is active.

    LinGHub only works in onboard mode; host mode means another tool has
    taken the mouse over.
    """


class NodeMismatch(Exception):
    """The node the ratbagd path names cannot be confirmed as a Logitech device."""


class NodeGone(Exception):
    """The node the ratbagd path names no longer exists.

    ratbagd lags the kernel by about 2 s when a device goes, so for a moment
    it still lists a mouse whose node the kernel has removed. The mouse is
    gone, not unconfirmed. Deliberately not a NodeMismatch.
    """


class Transport(Protocol):
    def write(self, data: bytes) -> None: ...

    def read(self, timeout: float) -> bytes | None: ...

    def close(self) -> None: ...


class HidrawTransport:
    """A hidraw node, opened for one read."""

    def __init__(self, path: Path):
        # PermissionError and FileNotFoundError surface from here unchanged:
        # the caller tells a refused node from a gone one.
        self._fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)

    def write(self, data: bytes) -> None:
        os.write(self._fd, data)

    def read(self, timeout: float) -> bytes | None:
        ready, _, _ = select.select([self._fd], [], [], max(timeout, 0))
        if not ready:
            return None
        try:
            return os.read(self._fd, 64)
        except BlockingIOError:
            return None

    def close(self) -> None:
        os.close(self._fd)


def node_for(device_path: str, sys_root: Path = Path("/sys/class/hidraw")) -> Path:
    """The /dev node behind a ratbagd device path, checked to be Logitech.

    ratbagd names its device objects after the hidraw node. That is how it
    behaves, not a promise, so the node is checked: if the name ever stops
    meaning that, this refuses rather than reading another device.
    """
    name = device_path.rstrip("/").rsplit("/", 1)[-1]
    if not _NODE_NAME.match(name):
        raise NodeMismatch(f"{device_path} does not name a hidraw node")
    if not (sys_root / name).exists():
        raise NodeGone(f"{name} is no longer in sysfs")
    try:
        uevent = (sys_root / name / "device" / "uevent").read_text()
    except OSError as exc:
        raise NodeMismatch(f"cannot read {name} in sysfs: {exc}") from exc
    hid_id = next(
        (line.split("=", 1)[1] for line in uevent.splitlines() if line.startswith("HID_ID=")),
        "",
    )
    if _LOGITECH not in hid_id.upper().split(":"):
        raise NodeMismatch(f"{name} is not a Logitech device (HID_ID={hid_id or 'missing'})")
    return Path("/dev") / name


class OnboardProfiles:
    """The onboard profiles feature of one mouse, reached through a node.

    The device address and the feature's index are found on the first read
    and kept: they hold for as long as this connection to the mouse does.
    """

    def __init__(self, open_transport: Callable[[], Transport], timeout: float = 0.5):
        self._open = open_transport
        self._timeout = timeout
        self._address: int | None = None
        self._feature: int | None = None

    def active_slot(self) -> int:
        """The slot the mouse is on.

        Raises NoReply, HidppError or HostMode when the mouse cannot say,
        and OSError when the node cannot be opened or used.
        """
        transport = self._open()
        try:
            if self._address is None:
                self._address, self._feature = self._find(transport)
            mode = self._request(transport, self._address, self._feature, _GET_ONBOARD_MODE)[0]
            if mode == _HOST_MODE:
                raise HostMode("the mouse is in host mode")
            reply = self._request(transport, self._address, self._feature, _GET_CURRENT_PROFILE)
        finally:
            transport.close()
        number = (reply[0] << 8) | reply[1]
        return number - 1

    def _find(self, transport: Transport) -> tuple[int, int]:
        """Which address answers, and where it keeps the 0x8100 feature."""
        failure: Exception = NoReply("no address answered")
        for address in (WIRED, RECEIVER):
            try:
                params = self._request(
                    transport, address, _ROOT, _GET_FEATURE,
                    bytes([ONBOARD_PROFILES >> 8, ONBOARD_PROFILES & 0xFF]),
                )
            except (NoReply, HidppError) as exc:
                failure = exc
                continue
            if params[0] == 0:
                raise HidppError("the mouse has no onboard profiles feature (0x8100)")
            return address, params[0]
        raise failure

    def _request(
        self, transport: Transport, address: int, feature: int, function: int,
        params: bytes = b"",
    ) -> bytes:
        """Send one request and return its reply's parameters."""
        function_sw = (function << 4) | SOFTWARE_ID
        transport.write(bytes([_LONG, address, feature, function_sw, *params]).ljust(20, b"\0"))
        deadline = time.monotonic() + self._timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining < 0:
                raise NoReply(f"no reply from address {address:#04x}")
            report = transport.read(remaining)
            if report is None:
                raise NoReply(f"no reply from address {address:#04x}")
            if len(report) < 6 or report[0] not in (_SHORT, _LONG) or report[1] != address:
                continue
            if report[2] in (_HIDPP20_ERROR, _HIDPP10_ERROR):
                if report[3] == feature and report[4] == function_sw:
                    raise HidppError(f"error {report[5]:#04x} from address {address:#04x}")
                continue
            if report[2] == feature and report[3] == function_sw:
                return report[4:]
