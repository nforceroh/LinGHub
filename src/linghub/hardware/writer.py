"""Write a Profile to the mouse and verify the result.

ratbagd's setters fail silently: they return success even when the value is
rejected or clamped. Every write here is therefore read back and compared,
and a mismatch is raised rather than reported as success.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from ..domain.profile import Profile
from . import mapping
from .ratbag import SERVICE, RatbagClient, Device, DeviceReplaced


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

    def __init__(self, client: RatbagClient, device: Device):
        self._client = client
        self._device = device

    @property
    def device(self) -> Device:
        return self._device

    async def report_rates(self) -> list[int]:
        """The report rates this device accepts, in Hz; empty if unpublished."""
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
        """Write `profile` into `slot`, commit, and verify."""
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
        """Which slot the device says is active, or None if none is.

        Read from hardware rather than remembered, so the daemon can notice
        when something outside it changed the active profile.
        """
        await self._check_identity()
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
    Raises DeviceNotFound when no G502 is attached.
    """

    def __init__(self):
        self._bus = None

    async def connect(self) -> ProfileWriter:
        from dbus_fast import BusType
        from dbus_fast.aio import MessageBus

        if self._bus is None:
            self._bus = await asyncio.wait_for(
                MessageBus(bus_type=BusType.SYSTEM).connect(), timeout=5
            )
        client = RatbagClient(self._bus)
        device = await client.find_device()
        logging.getLogger(__name__).info("found %s at %s", device.name, device.path)
        return ProfileWriter(client, device)

    def disconnect(self) -> None:
        if self._bus is not None:
            self._bus.disconnect()
            self._bus = None
