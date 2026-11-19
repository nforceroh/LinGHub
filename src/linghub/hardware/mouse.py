"""The mouse as the daemon sees it: find it, confirm it, write to it, read it.

One module owns the connection rules that used to be spread over four:
finding the G502 through ratbagd, confirming that the hidraw node behind it
is really a Logitech device, re-checking identity before every write, and
translating every failure into the Mouse seam's vocabulary (#8, #11).

Reads go over HID++ and writes through ratbagd (ADR-0010). `ActiveSlotReader`
and `hidpp.OnboardProfiles` stay as they are: both are already deep.

ratbagd's setters fail silently: they return success even when the value is
rejected or clamped. Every write here is therefore read back and compared,
and a mismatch is raised rather than reported as success.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from dbus_fast import DBusError, Variant

from ..domain.profile import Profile
from . import hidpp, mapping
from .active_slot import ActiveSlotReader, MouseSlot, SlotReadings
from .failures import LoadRefused, MouseAbsent, MouseFailure, MouseLost
from .ratbag import NOT_FOUND, RatbagClient, Device, DeviceReplaced

logger = logging.getLogger(__name__)

# What a vanished mouse or a broken ratbagd looks like from down here: D-Bus
# errors arrive as RuntimeError (DeviceReplaced among them), a gone hidraw
# node as OSError.
_UNREACHABLE = (RuntimeError, OSError, DBusError, EOFError)


@contextlib.contextmanager
def _translated(refused: tuple[type[BaseException], ...] = ()):
    """Turn failures from below into the Mouse seam's vocabulary (#8).

    The one place where the order of these clauses matters: a WriteError is
    a RuntimeError, so refusals are matched first. Errors this doesn't
    recognise propagate untouched; they are bugs, and the daemon logs them
    with their traceback.
    """
    try:
        yield
    except MouseFailure:
        raise
    except refused as exc:
        raise LoadRefused(str(exc)) from exc
    except _UNREACHABLE as exc:
        raise MouseLost(str(exc)) from exc


async def _report_rates(client: RatbagClient, device: Device) -> list[int]:
    """The report rates this device accepts, in Hz; empty if unpublished.

    Read by `connect` and handed to the daemon with the mouse, so nothing
    asks a connected mouse a question that can fail.
    """
    with _translated():
        return await client.report_rates(device)


def _payloads_match(actual, expected) -> bool:
    """Compare a mapping payload, tolerating dbus-fast's Variant wrapping.

    Macro payloads arrive as a list of (event, value) tuples; scalars arrive
    bare or wrapped in a Variant depending on the signature.
    """
    if isinstance(actual, Variant):
        actual = actual.value
    if isinstance(expected, Variant):
        expected = expected.value

    if isinstance(actual, (list, tuple)) and isinstance(expected, (list, tuple)):
        if len(actual) != len(expected):
            return False
        return all(
            tuple(a) == tuple(e) for a, e in zip(actual, expected)
        )
    return actual == expected


class WriteError(RuntimeError):
    """A write did not take effect."""


@dataclass(frozen=True)
class WriteResult:
    """What a load changed, so the daemon can say so in its log."""

    changed: tuple[str, ...]


class RatbagMouse:
    """One connected G502: the daemon's Mouse protocol, plus what status shows.

    Built by `connect`, which is the only place that decides whether a
    connection succeeds. Everything below it is already known to be the
    right device.
    """

    def __init__(self, client: RatbagClient, device: Device, mouse: MouseSlot | None = None):
        """`mouse` reads the active slot from the mouse itself (#2); without
        one, ratbagd's answer is the only one."""
        self._client = client
        self._device = device
        self._slots = ActiveSlotReader(self._believed_slot, mouse)

    @property
    def device(self) -> Device:
        return self._device

    async def apply(self, profile: Profile, slot: int) -> WriteResult:
        """Write `profile` into `slot`, commit, verify, and activate it.

        Raises LoadRefused if the mouse or ratbagd won't take it (including a
        binding the encoder can't encode), MouseLost if the mouse is gone.
        """
        with _translated(refused=(WriteError, mapping.BindingError)):
            return await self._apply(profile, slot)

    async def active_slot(self) -> int | None:
        """The active slot, as the mouse reports it.

        Read each time rather than remembered, so the daemon notices when
        something outside it moved the mouse. Raises SlotUnknown when the
        mouse cannot say, MouseLost if it is gone; see `ActiveSlotReader`.
        """
        with _translated():
            await self._check_identity()
            return await self._slots.read()

    async def slot_readings(self) -> SlotReadings:
        """The mouse's answer and ratbagd's belief, side by side (#5).

        For showing, not deciding: `active_slot` is what the daemon acts on.
        Raises MouseLost if the mouse is gone.
        """
        with _translated():
            await self._check_identity()
            return await self._slots.readings()

    async def _check_identity(self) -> None:
        """Fail if the device path no longer names the device we found.

        ratbagd paths follow hidraw node numbers, which the kernel reuses
        when a wireless receiver reconnects. Without this check the mouse
        would carry on against whatever device inherited the path.
        """
        name = await self._client.get(self._device.path, "Device", "Name")
        if name != self._device.name:
            raise DeviceReplaced(
                f"{self._device.path} is now {name!r}, not {self._device.name!r}"
            )

    async def _believed_slot(self) -> int | None:
        """Which slot ratbagd believes is active, or None if none is."""
        for profile in await self._client.profiles(self._device):
            if profile.active:
                return profile.index
        return None

    async def _profile_path(self, slot: int) -> str:
        paths = await self._client.get(self._device.path, "Device", "Profiles")
        if slot >= len(paths):
            raise WriteError(f"device has no profile slot {slot}")
        return paths[slot]

    async def _apply(self, profile: Profile, slot: int) -> WriteResult:
        await self._check_identity()
        path = await self._profile_path(slot)
        changed: list[str] = []

        if profile.report_rate is not None:
            await self._client.set(path, "Profile", "ReportRate", "u", profile.report_rate)
            changed.append("report_rate")

        for index, resolution in enumerate(profile.resolutions):
            await self._write_resolution(path, index, resolution)
            changed.append(f"resolution[{index}]")

        for index, binding in profile.bindings.items():
            await self._write_binding(path, index, binding)
            changed.append(f"binding[{index}]")

        for led in profile.leds:
            await self._write_led(path, led)
            changed.append(f"led[{led['index']}]")

        await self._client.invoke(self._device.path, "Device", "Commit")
        await self._wait_for_commit(path)
        await self._verify(path, profile)

        # Writing a profile does not make it the active one. Activate the slot
        # and commit again, otherwise the mouse keeps using whichever profile
        # was active before.
        await self._client.invoke(path, "Profile", "SetActive")
        if not await self._client.get(path, "Profile", "IsActive"):
            raise WriteError(f"profile slot {slot} did not become active")
        await self._client.invoke(self._device.path, "Device", "Commit")
        await self._wait_for_commit(path)

        return WriteResult(changed=tuple(changed))

    async def _write_resolution(self, profile_path: str, index: int, resolution: dict) -> None:
        paths = await self._client.get(profile_path, "Profile", "Resolutions")
        if index >= len(paths):
            raise WriteError(f"profile has no resolution slot {index}")
        path = paths[index]

        if "dpi" in resolution:
            await self._client.set(
                path, "Resolution", "Resolution", "v", Variant("u", resolution["dpi"])
            )
        if "disabled" in resolution:
            await self._client.set(
                path, "Resolution", "IsDisabled", "b", bool(resolution["disabled"])
            )
        if resolution.get("default"):
            await self._client.invoke(path, "Resolution", "SetDefault")
        if resolution.get("active"):
            await self._client.invoke(path, "Resolution", "SetActive")

    async def _write_binding(self, profile_path: str, index: int, binding) -> None:
        paths = await self._client.get(profile_path, "Profile", "Buttons")
        if index >= len(paths):
            raise WriteError(f"profile has no button {index}")
        path = paths[index]

        action_type, payload = mapping.encode(binding)
        signature = "a(uu)" if action_type == mapping.ACTION_MACRO else "u"

        await self._client.set(
            path, "Button", "Mapping", "(uv)",
            (action_type, Variant(signature, payload)),
        )

    async def _write_led(self, profile_path: str, led: dict) -> None:
        paths = await self._client.get(profile_path, "Profile", "Leds")
        index = led["index"]
        if index >= len(paths):
            raise WriteError(f"profile has no LED {index}")
        path = paths[index]

        modes = {"off": 0, "on": 1, "cycle": 2, "breathing": 3}
        if "mode" in led:
            await self._client.set(path, "Led", "Mode", "u", modes[led["mode"]])
        if "duration" in led:
            await self._client.set(path, "Led", "EffectDuration", "u", led["duration"])
        if "brightness" in led:
            await self._client.set(path, "Led", "Brightness", "u", led["brightness"])
        if "color" in led:
            r, g, b = led["color"]
            await self._client.set(path, "Led", "Color", "(uuu)", (r, g, b))

    async def _wait_for_commit(self, profile_path: str, timeout: float = 5.0) -> None:
        """Wait for IsDirty to clear, which is the only completion signal.

        ratbagd emits no commit-complete signal and returns from Commit()
        immediately, so polling IsDirty is the practical way to know the
        write reached the device.
        """
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if not await self._client.get(profile_path, "Profile", "IsDirty"):
                return
            await asyncio.sleep(0.05)
        raise WriteError("commit did not complete within the timeout")

    async def _verify(self, profile_path: str, profile: Profile) -> None:
        """Read back what we wrote and fail on any mismatch."""
        if profile.report_rate is not None:
            actual = await self._client.get(profile_path, "Profile", "ReportRate")
            if actual != profile.report_rate:
                raise WriteError(
                    f"report rate did not take effect: wrote {profile.report_rate}, read {actual}"
                )

        for index, binding in profile.bindings.items():
            paths = await self._client.get(profile_path, "Profile", "Buttons")
            actual_type, actual_payload = await self._client.get(
                paths[index], "Button", "Mapping"
            )
            expected_type, expected_payload = mapping.encode(binding)
            if actual_type != expected_type:
                raise WriteError(
                    f"button {index} action type did not take effect: "
                    f"wrote {expected_type}, read {actual_type}"
                )
            # The payload matters as much as the type: ACTION_KEY with the
            # wrong keycode is a different binding that looks identical if you
            # only compare types.
            if not _payloads_match(actual_payload, expected_payload):
                raise WriteError(
                    f"button {index} value did not take effect: "
                    f"wrote {expected_payload!r}, read {actual_payload!r}"
                )


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
        raise MouseAbsent(NOT_FOUND) from exc
    except hidpp.NodeMismatch as exc:
        logger.error(
            "cannot read the active slot from the mouse: %s; using ratbagd's answer", exc
        )
        return None
    return hidpp.OnboardProfiles(lambda: open_node(node))


@dataclass(frozen=True)
class RatbagConnection:
    """A mouse that is ready to use, and what it can do.

    The capabilities come back with the mouse rather than from a second call
    the caller could get wrong: asking a connected mouse for its report rates
    can fail, and at connect time that is a mouse that isn't there. One
    connection, one step that can fail.
    """

    mouse: RatbagMouse
    report_rates: list[int]


async def connect(
    bus, *, sys_root: Path = Path("/sys/class/hidraw")
) -> RatbagConnection:
    """Find the G502 through ratbagd and return it ready to use.

    The one place that decides whether a connection succeeds: the device is
    found, the hidraw node behind it is confirmed, the mouse is built, and
    its capabilities are read. Raises MouseAbsent (not found, or a node the
    kernel already removed), MouseMisconfigured (two G502s, an unsupported
    ratbagd) or MouseLost (the mouse vanished before it could be asked), and
    nothing else on purpose.
    """
    client = RatbagClient(bus)
    device = await client.find_device()
    # Before announcing the find: ratbagd can still list a mouse the kernel
    # has removed, and mouse_for raises MouseAbsent for that.
    mouse = mouse_for(device.path, sys_root=sys_root)
    found = RatbagMouse(client, device, mouse=mouse)
    rates = await _report_rates(client, device)
    logger.info("found %s at %s (report rates %s)", device.name, device.path, rates)
    return RatbagConnection(found, rates)


class RatbagConnector:
    """Owns the system bus, and reconnects through `connect`.

    The production adapter for the daemon's mouse connection. It reuses the
    bus across reconnects and closes it on disconnect; the connection rules
    themselves live in `connect`.
    """

    def __init__(self, connect_bus=None, sys_root: Path = Path("/sys/class/hidraw")):
        """`connect_bus` makes the system bus connection; the tests pass a fake."""
        self._connect_bus = connect_bus or _system_bus
        self._sys_root = sys_root
        self._bus = None

    async def connect(self) -> RatbagConnection:
        try:
            if self._bus is None:
                self._bus = await asyncio.wait_for(self._connect_bus(), timeout=5)
            return await connect(self._bus, sys_root=self._sys_root)
        except MouseFailure:
            raise
        except _UNREACHABLE as exc:
            # A bus that failed may be broken for good: make a new one next time.
            self.disconnect()
            raise MouseAbsent(f"cannot reach the mouse through ratbagd: {exc}") from exc

    def disconnect(self) -> None:
        if self._bus is not None:
            self._bus.disconnect()
            self._bus = None


async def _system_bus():
    from dbus_fast import BusType
    from dbus_fast.aio import MessageBus

    return await MessageBus(bus_type=BusType.SYSTEM).connect()
