"""Tests for the profile writer's commit and activation sequence.

These use a fake RatbagClient so they run without hardware. The bug they
guard against is real: writing a profile does not make it active, so the
writer must call Profile.SetActive and commit again.
"""

import unittest

from linghub.domain.profile import Binding, Profile
from linghub.hardware.failures import LoadRefused, MouseLost
from linghub.hardware.mouse import RatbagMouse


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
        self.ignore_mapping_payload = False
        # What ratbagd says lives at the device path. A receiver reconnect
        # can renumber hidraw nodes, so this can become another device.
        self.device_name = "Logitech G502"

    async def call(self, message):
        from types import SimpleNamespace
        from dbus_fast import MessageType

        self.calls.append((message.path, message.member))
        return SimpleNamespace(message_type=MessageType.METHOD_RETURN, body=[0])

    async def get(self, path, interface, name):
        if name == "Name":
            return self.device_name
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

    async def set(self, path, interface, name, signature, value):
        self.calls.append((path, "Set"))
        if name == "ReportRate" and self.ignore_report_rate:
            # Simulate ratbagd accepting the write but not applying it.
            self._dirty = True
            return
        if name == "Mapping" and self.ignore_mapping_payload:
            # Simulate ratbagd accepting the write but keeping the old
            # payload: same action type, different value.
            action_type, _payload = value
            self._values[(path, name)] = (action_type, 999)
            self._dirty = True
            return
        self._values[(path, name)] = value
        self._dirty = True

    async def profiles(self, device):
        from linghub.hardware.ratbag import Profile

        return [
            Profile(index, path, path == self._active, False)
            for index, path in enumerate(self._profiles)
        ]

    async def invoke(self, path, interface, method):
        self.calls.append((path, method))
        if method == "Commit":
            self._dirty = False
        elif method == "SetActive":
            if self.fail_activation:
                return
            self._active = path


class FakeDevice:
    name = "Logitech G502"
    path = "/device"


class WriterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = FakeClient()
        self.writer = RatbagMouse(self.client, FakeDevice())

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
        with self.assertRaisesRegex(LoadRefused, "did not become active"):
            await self.writer.apply(profile, 1)

    async def test_raises_when_report_rate_does_not_take_effect(self):
        self.client.ignore_report_rate = True
        profile = Profile(name="desktop", report_rate=500)
        with self.assertRaisesRegex(LoadRefused, "report rate did not take effect"):
            await self.writer.apply(profile, 0)

    async def test_raises_when_the_keycode_does_not_take_effect(self):
        """The action type matching is not enough.

        A write that lands ACTION_KEY with the wrong keycode used to pass
        verification, because the payload was read and then never compared.
        """
        self.client.ignore_mapping_payload = True
        profile = Profile(name="desktop", bindings={0: Binding("key", "KEY_X")})
        with self.assertRaisesRegex(LoadRefused, "button 0"):
            await self.writer.apply(profile, 0)

    async def test_raises_when_a_macro_does_not_take_effect(self):
        self.client.ignore_mapping_payload = True
        profile = Profile(
            name="desktop",
            bindings={0: Binding("macro", "+KEY_LEFTCTRL +KEY_C -KEY_C -KEY_LEFTCTRL")},
        )
        with self.assertRaisesRegex(LoadRefused, "button 0"):
            await self.writer.apply(profile, 0)

    async def test_accepts_a_matching_payload(self):
        profile = Profile(name="desktop", bindings={0: Binding("key", "KEY_X")})
        await self.writer.apply(profile, 0)  # must not raise

    async def test_raises_for_missing_slot(self):
        profile = Profile(name="desktop")
        with self.assertRaisesRegex(LoadRefused, "no profile slot 9"):
            await self.writer.apply(profile, 9)

    async def test_raises_for_missing_button(self):
        profile = Profile(name="desktop", bindings={9: Binding("button", 1)})
        with self.assertRaisesRegex(LoadRefused, "no button 9"):
            await self.writer.apply(profile, 0)



class DeviceIdentityTests(unittest.IsolatedAsyncioTestCase):
    """ratbagd names devices by hidraw node, and nodes get reused.

    Seen on a G502 Lightspeed: after the receiver reconnected, the path the
    daemon held (/device/hidraw12) named the receiver's other device, a
    one-profile "Logitech Candy". Every load then failed with "no profile
    slot 1", read as a refused write, and was retried on the wrong device
    for good while the mouse sat on slot 0.
    """

    def setUp(self):
        self.client = FakeClient()
        self.writer = RatbagMouse(self.client, FakeDevice())
        self.client.device_name = "Logitech Candy"

    async def test_apply_reports_a_replaced_device_not_a_refused_write(self):
        with self.assertRaises(MouseLost):
            await self.writer.apply(Profile(name="world-of-tanks"), 1)

    async def test_apply_writes_nothing_to_the_other_device(self):
        with self.assertRaises(MouseLost):
            await self.writer.apply(Profile(name="desktop", report_rate=1000), 0)
        self.assertEqual(self.client.calls, [])

    async def test_active_slot_reports_a_replaced_device(self):
        with self.assertRaises(MouseLost):
            await self.writer.active_slot()

    async def test_a_replaced_device_is_lost_not_refused(self):
        self.assertFalse(issubclass(MouseLost, LoadRefused))



class ActiveSlotSourceTests(unittest.IsolatedAsyncioTestCase):
    """The writer's active slot comes from the mouse when it can (#2)."""

    async def test_the_mouse_answers_over_ratbagd(self):
        class Mouse:
            def active_slot(self):
                return 0

        client = FakeClient()
        client._active = "/p1"          # ratbagd believes slot 1
        writer = RatbagMouse(client, FakeDevice(), mouse=Mouse())
        self.assertEqual(await writer.active_slot(), 0)

    async def test_without_a_mouse_reader_ratbagd_answers(self):
        client = FakeClient()
        client._active = "/p1"
        self.assertEqual(await RatbagMouse(client, FakeDevice()).active_slot(), 1)

    async def test_a_replaced_device_is_found_before_the_mouse_is_asked(self):
        class Mouse:
            def active_slot(self):
                raise AssertionError("asked the mouse behind a replaced path")

        client = FakeClient()
        client.device_name = "Logitech Candy"
        with self.assertRaises(MouseLost):
            await RatbagMouse(client, FakeDevice(), mouse=Mouse()).active_slot()


if __name__ == "__main__":
    unittest.main()
