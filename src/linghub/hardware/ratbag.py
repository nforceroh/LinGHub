"""Minimal client for ratbagd's system D-Bus profile API."""

import asyncio
from dataclasses import dataclass

from dbus_fast import Message, MessageType, Variant
from dbus_fast.aio import MessageBus


SERVICE = "org.freedesktop.ratbag1"
ROOT = "/org/freedesktop/ratbag1"
PROPERTIES = "org.freedesktop.DBus.Properties"


@dataclass(frozen=True)
class Profile:
    index: int
    path: str
    active: bool
    disabled: bool


@dataclass(frozen=True)
class Device:
    name: str
    path: str


class DeviceNotFound(RuntimeError):
    """No matching device is visible to ratbagd.

    Distinct from other failures because it is usually transient: the device
    may be unplugged, or a stale process may be holding a deleted hidraw node.
    The daemon retries rather than exiting.
    """


class DeviceReplaced(RuntimeError):
    """The device path now names a different device.

    ratbagd names devices after their hidraw node, and the kernel reuses
    node numbers: after a wireless receiver reconnects, the path found at
    startup can name the receiver's other device. Distinct from WriteError
    because the cure is to find the mouse again, not to retry the write.
    """


class RatbagClient:
    """Use an already-connected system bus to manage a single G502."""

    def __init__(self, bus: MessageBus):
        self._bus = bus

    async def _call(self, message: Message) -> Message:
        try:
            reply = await asyncio.wait_for(self._bus.call(message), timeout=5)
        except TimeoutError as exc:
            raise RuntimeError(f"D-Bus call {message.member} timed out") from exc
        if reply.message_type == MessageType.ERROR:
            detail = reply.body[0] if reply.body else reply.error_name
            raise RuntimeError(f"D-Bus call {message.member} failed: {detail}")
        return reply

    async def _property(self, path: str, interface: str, name: str):
        reply = await self._call(Message(
            destination=SERVICE, path=path, interface=PROPERTIES, member="Get",
            signature="ss", body=[f"{SERVICE}.{interface}", name],
        ))
        value = reply.body[0]
        if not isinstance(value, Variant):
            raise RuntimeError(f"invalid D-Bus response for {interface}.{name}")
        return value.value

    async def _method(self, path: str, interface: str, method: str) -> None:
        reply = await self._call(Message(
            destination=SERVICE, path=path,
            interface=f"{SERVICE}.{interface}", member=method,
        ))
        if reply.body[0] != 0:
            raise RuntimeError(f"{interface}.{method} returned error {reply.body[0]}")

    async def find_device(self) -> Device:
        version = await self._property(ROOT, "Manager", "APIVersion")
        if version != 2:
            raise RuntimeError(f"unsupported ratbagd API version {version} (expected 2)")
        paths = await self._property(ROOT, "Manager", "Devices")
        matches = []
        for path in paths:
            name = await self._property(path, "Device", "Name")
            if "G502" in name:
                matches.append(Device(name, path))
        if not matches:
            from .diagnose import describe_failure

            raise DeviceNotFound(describe_failure())
        if len(matches) > 1:
            raise RuntimeError("multiple G502 devices found; cannot choose safely")
        return matches[0]

    async def report_rates(self, device: Device) -> list[int]:
        """The report rates this device accepts, in Hz.

        Read from the hardware profile rather than a table in this repo, so a
        variant offering a different set is not presented with wrong choices.
        Returns an empty list if the device does not publish them, because a
        missing capability must not stop the daemon from starting.
        """
        try:
            profiles = await self.profiles(device)
            if not profiles:
                return []
            return [
                int(rate)
                for rate in await self._property(profiles[0].path, "Profile", "ReportRates")
            ]
        except (RuntimeError, OSError):
            return []

    async def profiles(self, device: Device) -> list[Profile]:
        paths = await self._property(device.path, "Device", "Profiles")
        profiles = []
        for path in paths:
            index = await self._property(path, "Profile", "Index")
            active = await self._property(path, "Profile", "IsActive")
            disabled = await self._property(path, "Profile", "Disabled")
            profiles.append(Profile(index, path, active, disabled))
        return profiles

    async def switch(self, device: Device, index: int) -> bool:
        """Select a profile and queue its commit; return False if already active."""
        selected = next((p for p in await self.profiles(device) if p.index == index), None)
        if selected is None:
            raise RuntimeError(f"profile {index} not found")
        if selected.active:
            return False
        if selected.disabled:
            raise RuntimeError(f"profile {index} is disabled")
        await self._method(selected.path, "Profile", "SetActive")
        if not await self._property(selected.path, "Profile", "IsActive"):
            raise RuntimeError(f"ratbagd did not activate profile {index}")
        await self._method(device.path, "Device", "Commit")
        return True
