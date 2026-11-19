"""The Mouse seam speaks one failure vocabulary (#8).

Whatever fails underneath (D-Bus, ratbagd, hidraw, the encoder), the public
methods of ProfileWriter and RatbagConnector raise only the family in
`hardware.failures`, so the daemon can match on meaning instead of on
exception base classes whose order in an `except` list mattered.
"""

import errno
import tempfile
import unittest
from pathlib import Path

from linghub.domain.profile import Binding, Profile
from linghub.hardware import failures
from linghub.hardware.failures import (
    LoadRefused, MouseAbsent, MouseFailure, MouseLost, MouseMisconfigured, SlotUnknown,
)
from linghub.hardware.writer import ProfileWriter, RatbagConnector

from .test_ratbag import FakeBus
from .test_writer import FakeClient, FakeDevice


class FamilyTests(unittest.TestCase):
    def test_every_outcome_is_in_the_family(self):
        for outcome in (MouseAbsent, MouseMisconfigured, MouseLost, LoadRefused, SlotUnknown):
            with self.subTest(outcome=outcome.__name__):
                self.assertTrue(issubclass(outcome, MouseFailure))

    def test_the_family_is_not_what_lower_modules_raise(self):
        """Not RuntimeError or OSError, so nothing joins it by accident."""
        self.assertFalse(issubclass(MouseFailure, (RuntimeError, OSError, ValueError)))

    def test_slot_unknown_is_the_same_class_everywhere(self):
        from linghub.hardware import active_slot

        self.assertIs(active_slot.SlotUnknown, failures.SlotUnknown)


class FailingClient(FakeClient):
    """A fake ratbagd whose next call fails with `error`."""

    def __init__(self, error=None, **kwargs):
        super().__init__(**kwargs)
        self.error = error

    async def report_rates(self, device):
        if self.error is not None:
            raise self.error
        return [1000]

    async def _property(self, path, interface, name):
        if self.error is not None and name != "Name":
            raise self.error
        return await super()._property(path, interface, name)


class WriterTests(unittest.IsolatedAsyncioTestCase):
    def _writer(self, error=None, **kwargs):
        self.client = FailingClient(error, **kwargs)
        return ProfileWriter(self.client, FakeDevice())

    async def test_an_unencodable_binding_is_a_refused_load(self):
        """The crash: BindingError is a ValueError nothing in the daemon caught."""
        profile = Profile(name="desktop", bindings={0: Binding("key", "KEY_BOGUS")})
        with self.assertRaisesRegex(LoadRefused, "KEY_BOGUS"):
            await self._writer().apply(profile, 0)

    async def test_a_write_that_does_not_take_is_a_refused_load(self):
        writer = self._writer()
        self.client.ignore_report_rate = True
        with self.assertRaises(LoadRefused):
            await writer.apply(Profile(name="desktop", report_rate=500), 0)

    async def test_a_missing_slot_is_a_refused_load(self):
        with self.assertRaisesRegex(LoadRefused, "no profile slot 9"):
            await self._writer().apply(Profile(name="desktop"), 9)

    async def test_a_dbus_failure_while_writing_is_a_lost_mouse(self):
        writer = self._writer(RuntimeError("D-Bus call Get failed: Unknown object"))
        with self.assertRaises(MouseLost):
            await writer.apply(Profile(name="desktop"), 0)

    async def test_a_replaced_device_is_a_lost_mouse(self):
        writer = self._writer()
        self.client.device_name = "Logitech Candy"
        with self.assertRaises(MouseLost):
            await writer.apply(Profile(name="desktop"), 0)
        with self.assertRaises(MouseLost):
            await writer.active_slot()

    async def test_a_gone_node_while_reading_the_slot_is_a_lost_mouse(self):
        class Gone:
            def active_slot(self):
                raise FileNotFoundError(errno.ENOENT, "gone")

        writer = ProfileWriter(FailingClient(), FakeDevice(), mouse=Gone())
        with self.assertRaises(MouseLost):
            await writer.active_slot()

    async def test_slot_unknown_passes_through(self):
        from linghub.hardware import hidpp

        class Asleep:
            def active_slot(self):
                raise hidpp.NoReply("no reply")

        writer = ProfileWriter(FailingClient(), FakeDevice(), mouse=Asleep())
        with self.assertRaises(SlotUnknown):
            await writer.active_slot()

    async def test_a_dbus_failure_reading_report_rates_is_a_lost_mouse(self):
        writer = self._writer(RuntimeError("D-Bus call Get failed"))
        with self.assertRaises(MouseLost):
            await writer.report_rates()

    async def test_a_bug_is_not_dressed_up_as_an_outcome(self):
        """An error the adapter doesn't recognise propagates: the daemon's
        catch-all logs it with its traceback."""
        writer = self._writer(ZeroDivisionError("a bug"))
        with self.assertRaises(ZeroDivisionError):
            await writer.apply(Profile(name="desktop"), 0)


class SlotReadingsTests(unittest.IsolatedAsyncioTestCase):
    """The writer's public view of both answers, for `linghub status` (#5)."""

    async def test_both_answers(self):
        class Mouse:
            def active_slot(self):
                return 0

        client = FailingClient()
        client._active = "/p1"                    # ratbagd believes slot 1
        readings = await ProfileWriter(client, FakeDevice(), mouse=Mouse()).slot_readings()
        self.assertEqual((readings.mouse, readings.believed), (0, 1))

    async def test_a_replaced_device_is_a_lost_mouse(self):
        client = FailingClient()
        client.device_name = "Logitech Candy"
        with self.assertRaises(MouseLost):
            await ProfileWriter(client, FakeDevice()).slot_readings()

    async def test_a_dbus_failure_is_a_lost_mouse(self):
        writer = ProfileWriter(FailingClient(RuntimeError("D-Bus call Get failed")), FakeDevice())
        with self.assertRaises(MouseLost):
            await writer.slot_readings()


class FailingBus(FakeBus):
    def __init__(self, error=None):
        super().__init__()
        self.error = error

    async def call(self, message):
        if self.error is not None:
            raise self.error
        return await super().call(message)

    def disconnect(self):
        pass


class ConnectorTests(unittest.IsolatedAsyncioTestCase):
    """RatbagConnector had no tests before #8."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.sys = Path(directory.name)

    def _connector(self, bus):
        async def connect_bus():
            return bus

        return RatbagConnector(connect_bus=connect_bus, sys_root=self.sys)

    def _devices(self, bus, *devices):
        from linghub.hardware.ratbag import ROOT

        bus.values[(ROOT, "Manager", "Devices")] = ("ao", [path for path, _ in devices])
        for path, name in devices:
            bus.values[(path, "Device", "Name")] = ("s", name)

    def _node(self, name, hid_id="0003:0000046D:0000407F"):
        uevent = self.sys / name / "device" / "uevent"
        uevent.parent.mkdir(parents=True)
        uevent.write_text(f"HID_ID={hid_id}\n")

    async def test_a_g502_on_a_logitech_node_connects(self):
        bus = FailingBus()
        self._devices(bus, ("/org/freedesktop/ratbag1/device/hidraw31", "Logitech G502"))
        self._node("hidraw31")
        mouse = await self._connector(bus).connect()
        self.assertEqual(mouse.device.path, "/org/freedesktop/ratbag1/device/hidraw31")

    async def test_no_g502_is_absent(self):
        bus = FailingBus()
        self._devices(bus, ("/org/freedesktop/ratbag1/device/hidraw32", "Logitech Candy"))
        with self.assertRaisesRegex(MouseAbsent, "no G502 found"):
            await self._connector(bus).connect()

    async def test_ratbagd_not_answering_is_absent_and_says_so(self):
        bus = FailingBus(RuntimeError("org.freedesktop.DBus.Error.ServiceUnknown"))
        with self.assertRaisesRegex(MouseAbsent, "ratbagd"):
            await self._connector(bus).connect()

    async def test_the_race_with_the_kernel_is_absent(self):
        """ratbagd still lists a mouse whose node the kernel already removed."""
        bus = FailingBus()
        self._devices(bus, ("/org/freedesktop/ratbag1/device/hidraw31", "Logitech G502"))
        with self.assertRaisesRegex(MouseAbsent, "no G502 found"):
            await self._connector(bus).connect()

    async def test_two_g502s_are_misconfigured(self):
        bus = FailingBus()
        self._devices(
            bus,
            ("/org/freedesktop/ratbag1/device/hidraw31", "Logitech G502"),
            ("/org/freedesktop/ratbag1/device/hidraw40", "Logitech G502 HERO"),
        )
        with self.assertRaisesRegex(MouseMisconfigured, "multiple G502"):
            await self._connector(bus).connect()

    async def test_an_unsupported_ratbagd_is_misconfigured(self):
        from linghub.hardware.ratbag import ROOT

        bus = FailingBus()
        bus.values[(ROOT, "Manager", "APIVersion")] = ("i", 1)
        with self.assertRaisesRegex(MouseMisconfigured, "API version"):
            await self._connector(bus).connect()

    async def test_a_session_bus_that_cannot_connect_is_absent(self):
        async def connect_bus():
            raise OSError(errno.ENOENT, "no system bus")

        with self.assertRaisesRegex(MouseAbsent, "ratbagd"):
            await RatbagConnector(connect_bus=connect_bus, sys_root=self.sys).connect()


if __name__ == "__main__":
    unittest.main()
