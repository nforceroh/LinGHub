"""Tests for the profile writer's commit and activation sequence.

These use a fake RatbagClient so they run without hardware. The bug they
guard against is real: writing a profile does not make it active, so the
writer must call Profile.SetActive and commit again.
"""

import unittest

from linghub.domain.profile import Binding, Profile
from linghub.hardware.writer import ProfileWriter, WriteError


class FakeClient:
    """Minimal stand-in for RatbagClient, recording every call."""

    def __init__(self, profiles=("/p0", "/p1"), buttons=("/b0", "/b1"),
                 resolutions=("/r0",), leds=("/l0",)):
        self.calls = []
        self._profiles = list(profiles)
        self._buttons = list(buttons)
        self._resolutions = list(resolutions)
        self._leds = list(leds)
        self._values = {}
        self._active = "/p0"
        self._dirty = False
        self.fail_activation = False
        self.ignore_report_rate = False

    async def _call(self, message):
        from types import SimpleNamespace
        from dbus_fast import MessageType, Variant

        self.calls.append((message.path, message.member))
        if message.member == "Set":
            interface, name, variant = message.body
            if name == "ReportRate" and self.ignore_report_rate:
                # Simulate ratbagd accepting the write but not applying it.
                self._dirty = True
                return SimpleNamespace(message_type=MessageType.METHOD_RETURN, body=[0])
            self._values[(message.path, name)] = variant.value
            self._dirty = True
        return SimpleNamespace(message_type=MessageType.METHOD_RETURN, body=[0])

    async def _property(self, path, interface, name):
        if name == "Profiles":
            return self._profiles
        if name == "Buttons":
            return self._buttons
        if name == "Resolutions":
            return self._resolutions
        if name == "Leds":
            return self._leds
        if name == "IsDirty":
            return self._dirty
        if name == "IsActive":
            return path == self._active
        if name == "ReportRate":
            return self._values.get((path, "ReportRate"), 1000)
        if name == "Mapping":
            return self._values.get((path, "Mapping"), (1, 1))
        raise AssertionError(f"unexpected property {name}")

    async def _method(self, path, interface, method):
        self.calls.append((path, method))
        if method == "Commit":
            self._dirty = False
        elif method == "SetActive":
            if self.fail_activation:
                return
            self._active = path


class FakeDevice:
    path = "/device"


class WriterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = FakeClient()
        self.writer = ProfileWriter(self.client, FakeDevice())

    async def test_activates_the_slot_after_writing(self):
        profile = Profile(name="desktop", bindings={0: Binding("button", 1)})
        await self.writer.apply(profile, 1)
        self.assertIn(("/p1", "SetActive"), self.client.calls)

    async def test_commits_after_activation(self):
        profile = Profile(name="desktop", bindings={0: Binding("button", 1)})
        await self.writer.apply(profile, 1)
        commits = [i for i, call in enumerate(self.client.calls) if call[1] == "Commit"]
        activate = self.client.calls.index(("/p1", "SetActive"))
        self.assertTrue(any(i > activate for i in commits),
                        "expected a Commit after SetActive")

    async def test_raises_when_slot_does_not_become_active(self):
        self.client.fail_activation = True
        profile = Profile(name="desktop", bindings={0: Binding("button", 1)})
        with self.assertRaisesRegex(WriteError, "did not become active"):
            await self.writer.apply(profile, 1)

    async def test_raises_when_report_rate_does_not_take_effect(self):
        self.client.ignore_report_rate = True
        profile = Profile(name="desktop", report_rate=500)
        with self.assertRaisesRegex(WriteError, "report rate did not take effect"):
            await self.writer.apply(profile, 0)

    async def test_raises_for_missing_slot(self):
        profile = Profile(name="desktop")
        with self.assertRaisesRegex(WriteError, "no profile slot 9"):
            await self.writer.apply(profile, 9)

    async def test_raises_for_missing_button(self):
        profile = Profile(name="desktop", bindings={9: Binding("button", 1)})
        with self.assertRaisesRegex(WriteError, "no button 9"):
            await self.writer.apply(profile, 0)


if __name__ == "__main__":
    unittest.main()
