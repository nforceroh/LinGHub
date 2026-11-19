"""Write a Profile to the mouse and verify the result.

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

from dbus_fast import DBusError

from ..domain.profile import Profile
from . import mapping
from .active_slot import ActiveSlotReader, MouseSlot, mouse_for
from .failures import LoadRefused, MouseAbsent, MouseFailure, MouseLost
from .ratbag import SERVICE, RatbagClient, Device, DeviceReplaced

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


def _payloads_match(actual, expected) -> bool:
    """Compare a mapping payload, tolerating dbus-fast's Variant wrapping.

    Macro payloads arrive as a list of (event, value) tuples; scalars arrive
    bare or wrapped in a Variant depending on the signature.
    """
    from dbus_fast import Variant

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
    slot: int
    changed: tuple[str, ...]
    skipped: bool = False


class ProfileWriter:
    """Apply profiles to a device through an existing RatbagClient."""

    def __init__(self, client: RatbagClient, device: Device, mouse: MouseSlot | None = None):
        """`mouse` reads the active slot from the mouse itself (#2); without
        one, ratbagd's answer is the only one."""
        self._client = client
        self._device = device
        self._slots = ActiveSlotReader(self._believed_slot, mouse)

    @property
    def device(self) -> Device:
        return self._device

    async def report_rates(self) -> list[int]:
        """The report rates this device accepts, in Hz; empty if unpublished.

        Raises MouseLost if the mouse is gone.
        """
        with _translated():
            return await self._client.report_rates(self._device)

    async def _check_identity(self) -> None:
        """Fail if the device path no longer names the device we found.

        ratbagd paths follow hidraw node numbers, which the kernel reuses
        when a wireless receiver reconnects. Without this check the writer
        would carry on against whatever device inherited the path.
        """
        name = await self._client._property(self._device.path, "Device", "Name")
        if name != self._device.name:
            raise DeviceReplaced(
                f"{self._device.path} is now {name!r}, not {self._device.name!r}"
            )

    async def _profile_path(self, slot: int) -> str:
        paths = await self._client._property(self._device.path, "Device", "Profiles")
        if slot >= len(paths):
            raise WriteError(f"device has no profile slot {slot}")
        return paths[slot]

    async def _set(self, path: str, interface: str, name: str, signature: str, value) -> None:
        from dbus_fast import Message, Variant

        await self._client._call(Message(
            destination=SERVICE,
            path=path,
            interface="org.freedesktop.DBus.Properties",
            member="Set",
            signature="ssv",
            body=[f"{SERVICE}.{interface}", name, Variant(signature, value)],
        ))

    async def _get(self, path: str, interface: str, name: str):
        return await self._client._property(path, interface, name)

    async def apply(self, profile: Profile, slot: int) -> WriteResult:
        """Write `profile` into `slot`, commit, verify, and activate it.

        Raises LoadRefused if the mouse or ratbagd won't take it (including a
        binding the encoder can't encode), MouseLost if the mouse is gone.
        """
        with _translated(refused=(WriteError, mapping.BindingError)):
            return await self._apply(profile, slot)

    async def _apply(self, profile: Profile, slot: int) -> WriteResult:
        await self._check_identity()
        path = await self._profile_path(slot)
        changed: list[str] = []

        if profile.report_rate is not None:
            await self._set(path, "Profile", "ReportRate", "u", profile.report_rate)
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

        await self._client._method(self._device.path, "Device", "Commit")
        await self._wait_for_commit(path)
        await self._verify(path, profile)

        # Writing a profile does not make it the active one. Activate the slot
        # and commit again, otherwise the mouse keeps using whichever profile
        # was active before.
        await self._client._method(path, "Profile", "SetActive")
        if not await self._get(path, "Profile", "IsActive"):
            raise WriteError(f"profile slot {slot} did not become active")
        await self._client._method(self._device.path, "Device", "Commit")
        await self._wait_for_commit(path)

        return WriteResult(slot=slot, changed=tuple(changed))

    async def active_slot(self) -> int | None:
        """The active slot, as the mouse reports it.

        Read each time rather than remembered, so the daemon notices when
        something outside it moved the mouse. Raises SlotUnknown when the
        mouse cannot say, MouseLost if it is gone; see `active_slot` for the
        rules.
        """
        with _translated():
            await self._check_identity()
            return await self._slots.read()

    async def _believed_slot(self) -> int | None:
        """Which slot ratbagd believes is active, or None if none is."""
        paths = await self._get(self._device.path, "Device", "Profiles")
        for index, path in enumerate(paths):
            if await self._get(path, "Profile", "IsActive"):
                return index
        return None

    async def _write_resolution(self, profile_path: str, index: int, resolution: dict) -> None:
        paths = await self._get(profile_path, "Profile", "Resolutions")
        if index >= len(paths):
            raise WriteError(f"profile has no resolution slot {index}")
        path = paths[index]

        if "dpi" in resolution:
            from dbus_fast import Variant

            await self._set(path, "Resolution", "Resolution", "v", Variant("u", resolution["dpi"]))
        if "disabled" in resolution:
            await self._set(path, "Resolution", "IsDisabled", "b", bool(resolution["disabled"]))
        if resolution.get("default"):
            await self._client._method(path, "Resolution", "SetDefault")
        if resolution.get("active"):
            await self._client._method(path, "Resolution", "SetActive")

    async def _write_binding(self, profile_path: str, index: int, binding) -> None:
        from dbus_fast import Variant

        paths = await self._get(profile_path, "Profile", "Buttons")
        if index >= len(paths):
            raise WriteError(f"profile has no button {index}")
        path = paths[index]

        action_type, payload = mapping.encode(binding)
        signature = "a(uu)" if action_type == mapping.ACTION_MACRO else "u"

        await self._set(
            path, "Button", "Mapping", "(uv)",
            (action_type, Variant(signature, payload)),
        )

    async def _write_led(self, profile_path: str, led: dict) -> None:
        paths = await self._get(profile_path, "Profile", "Leds")
        index = led["index"]
        if index >= len(paths):
            raise WriteError(f"profile has no LED {index}")
        path = paths[index]

        modes = {"off": 0, "on": 1, "cycle": 2, "breathing": 3}
        if "mode" in led:
            await self._set(path, "Led", "Mode", "u", modes[led["mode"]])
        if "duration" in led:
            await self._set(path, "Led", "EffectDuration", "u", led["duration"])
        if "brightness" in led:
            await self._set(path, "Led", "Brightness", "u", led["brightness"])
        if "color" in led:
            r, g, b = led["color"]
            await self._set(path, "Led", "Color", "(uuu)", (r, g, b))

    async def _wait_for_commit(self, profile_path: str, timeout: float = 5.0) -> None:
        """Wait for IsDirty to clear, which is the only completion signal.

        ratbagd emits no commit-complete signal and returns from Commit()
        immediately, so polling IsDirty is the practical way to know the
        write reached the device.
        """
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if not await self._get(profile_path, "Profile", "IsDirty"):
                return
            await asyncio.sleep(0.05)
        raise WriteError("commit did not complete within the timeout")

    async def _verify(self, profile_path: str, profile: Profile) -> None:
        """Read back what we wrote and fail on any mismatch."""
        if profile.report_rate is not None:
            actual = await self._get(profile_path, "Profile", "ReportRate")
            if actual != profile.report_rate:
                raise WriteError(
                    f"report rate did not take effect: wrote {profile.report_rate}, read {actual}"
                )

        for index, binding in profile.bindings.items():
            paths = await self._get(profile_path, "Profile", "Buttons")
            actual_type, actual_payload = await self._get(paths[index], "Button", "Mapping")
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


class RatbagConnector:
    """Finds the G502 through ratbagd and hands back a writer for it.

    The production adapter for the daemon's mouse connection. It owns the
    system bus, reusing it across reconnects, and closes it on disconnect.
    `connect` raises MouseAbsent (not found, or ratbagd not answering) or
    MouseMisconfigured (two G502s, an unsupported ratbagd), and nothing else
    on purpose.
    """

    def __init__(self, connect_bus=None, sys_root: Path = Path("/sys/class/hidraw")):
        """`connect_bus` makes the system bus connection; the tests pass a fake."""
        self._connect_bus = connect_bus or _system_bus
        self._sys_root = sys_root
        self._bus = None

    async def connect(self) -> ProfileWriter:
        try:
            if self._bus is None:
                self._bus = await asyncio.wait_for(self._connect_bus(), timeout=5)
            client = RatbagClient(self._bus)
            device = await client.find_device()
            # Before announcing the find: ratbagd can still list a mouse the
            # kernel has removed, and mouse_for raises MouseAbsent for that.
            mouse = mouse_for(device.path, sys_root=self._sys_root)
        except MouseFailure:
            raise
        except _UNREACHABLE as exc:
            # A bus that failed may be broken for good: make a new one next time.
            self.disconnect()
            raise MouseAbsent(f"cannot reach the mouse through ratbagd: {exc}") from exc
        logging.getLogger(__name__).info("found %s at %s", device.name, device.path)
        return ProfileWriter(client, device, mouse=mouse)

    def disconnect(self) -> None:
        if self._bus is not None:
            self._bus.disconnect()
            self._bus = None


async def _system_bus():
    from dbus_fast import BusType
    from dbus_fast.aio import MessageBus

    return await MessageBus(bus_type=BusType.SYSTEM).connect()
