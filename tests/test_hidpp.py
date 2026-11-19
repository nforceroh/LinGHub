"""Tests for reading the active slot from the mouse over HID++ 2.0.

A fake device stands in for the hidraw node: it answers requests the way a
G502 does, wired or behind a receiver, and can stay silent, return errors, or
interleave replies meant for another process (ratbagd uses software id 0x8).
"""

import unittest
from pathlib import Path
import tempfile

from linghub.hardware import hidpp


FEATURE_INDEX = 0x0B


class FakeDevice:
    """A hidraw node with one G502 on it."""

    def __init__(self, *, address=hidpp.RECEIVER, mode=1, profile=2,
                 feature_index=FEATURE_INDEX):
        self.address = address
        self.mode = mode
        self.profile = profile
        self.feature_index = feature_index
        self.asleep = False
        self.errors: set[int] = set()        # functions answered with an error
        self.noise: list[bytes] = []         # sent before every reply
        self.sent: list[bytes] = []
        self.closed = 0
        self._pending: list[bytes] = []

    # --- transport -------------------------------------------------------

    def write(self, data: bytes) -> None:
        self.sent.append(bytes(data))
        self._pending.extend(self.noise)
        self._pending.extend(self._answer(bytes(data)))

    def read(self, timeout: float) -> bytes | None:
        return self._pending.pop(0) if self._pending else None

    def close(self) -> None:
        self.closed += 1

    # --- the device ------------------------------------------------------

    def _answer(self, data: bytes) -> list[bytes]:
        report, address, feature, function_sw = data[0], data[1], data[2], data[3]
        if address != self.address:
            if address == hidpp.WIRED and self.address == hidpp.RECEIVER:
                # The receiver itself answers the wired address, in HID++ 1.0.
                return [bytes([0x10, 0xFF, 0x8F, feature, function_sw, 0x01, 0x00])]
            return []
        if self.asleep:
            return []
        function = function_sw >> 4

        def reply(*params):
            return [bytes([0x11, address, feature, function_sw, *params]).ljust(20, b"\0")]

        if feature == 0x00 and function == 0:
            wanted = (data[4] << 8) | data[5]
            return reply(self.feature_index if wanted == 0x8100 else 0)
        if feature == self.feature_index and self.feature_index:
            if function in self.errors:
                return [bytes([0x11, address, 0xFF, feature, function_sw, 0x05]).ljust(20, b"\0")]
            if function == 2:
                return reply(self.mode)
            if function == 4:
                return reply(self.profile >> 8, self.profile & 0xFF)
        return []

    def requests_to_root(self) -> int:
        return sum(1 for d in self.sent if d[2] == 0x00 and d[1] == self.address)


def onboard(device: FakeDevice) -> hidpp.OnboardProfiles:
    return hidpp.OnboardProfiles(lambda: device, timeout=0.01)


class ActiveSlotTests(unittest.TestCase):
    def test_the_slot_is_the_profile_number_less_one(self):
        self.assertEqual(onboard(FakeDevice(profile=2)).active_slot(), 1)
        self.assertEqual(onboard(FakeDevice(profile=1)).active_slot(), 0)

    def test_requests_carry_our_software_id(self):
        device = FakeDevice()
        onboard(device).active_slot()
        self.assertTrue(device.sent)
        self.assertTrue(all(d[3] & 0x0F == hidpp.SOFTWARE_ID for d in device.sent))

    def test_our_software_id_is_not_libratbags_or_the_kernels(self):
        self.assertNotIn(hidpp.SOFTWARE_ID, (0x0, 0x1, 0x8))

    def test_the_transport_is_closed_after_every_read(self):
        """Opened per read: a node that a KVM switch deleted is never held."""
        device = FakeDevice()
        reader = onboard(device)
        reader.active_slot()
        reader.active_slot()
        self.assertEqual(device.closed, 2)

    def test_the_transport_is_closed_when_a_read_fails(self):
        device = FakeDevice()
        device.asleep = True
        with self.assertRaises(hidpp.NoReply):
            onboard(device).active_slot()
        self.assertEqual(device.closed, 1)


class AddressTests(unittest.TestCase):
    def test_a_mouse_behind_a_receiver_is_found(self):
        device = FakeDevice(address=hidpp.RECEIVER, profile=2)
        self.assertEqual(onboard(device).active_slot(), 1)

    def test_a_wired_mouse_is_found(self):
        device = FakeDevice(address=hidpp.WIRED, profile=1)
        self.assertEqual(onboard(device).active_slot(), 0)

    def test_the_wired_address_is_tried_first(self):
        device = FakeDevice(address=hidpp.WIRED)
        onboard(device).active_slot()
        self.assertEqual(device.sent[0][1], hidpp.WIRED)

    def test_the_address_and_feature_are_looked_up_once_per_connection(self):
        device = FakeDevice()
        reader = onboard(device)
        reader.active_slot()
        first = len(device.sent)
        reader.active_slot()
        self.assertEqual(len(device.sent) - first, 2, "only mode and profile the second time")

    def test_a_mouse_without_onboard_profiles_is_an_error(self):
        device = FakeDevice(feature_index=0)
        with self.assertRaises(hidpp.HidppError):
            onboard(device).active_slot()


class FailureTests(unittest.TestCase):
    def test_a_silent_mouse_is_no_reply(self):
        device = FakeDevice()
        device.asleep = True
        with self.assertRaises(hidpp.NoReply):
            onboard(device).active_slot()

    def test_a_mouse_that_falls_asleep_later_is_no_reply(self):
        device = FakeDevice()
        reader = onboard(device)
        reader.active_slot()
        device.asleep = True
        with self.assertRaises(hidpp.NoReply):
            reader.active_slot()

    def test_an_error_reply_is_a_hidpp_error(self):
        device = FakeDevice()
        device.errors = {4}
        with self.assertRaises(hidpp.HidppError):
            onboard(device).active_slot()

    def test_host_mode_is_its_own_failure(self):
        with self.assertRaises(hidpp.HostMode):
            onboard(FakeDevice(mode=2)).active_slot()

    def test_none_of_the_failures_is_a_runtime_error(self):
        """The daemon treats RuntimeError and OSError as a lost mouse."""
        for error in (hidpp.NoReply, hidpp.HidppError, hidpp.HostMode):
            with self.subTest(error=error.__name__):
                self.assertFalse(issubclass(error, (RuntimeError, OSError)))


class SharingTests(unittest.TestCase):
    """ratbagd and the kernel read the same node and see our replies too."""

    def test_replies_with_another_software_id_are_ignored(self):
        device = FakeDevice(profile=2)
        # ratbagd's reply to its own getCurrentProfile, saying profile 3.
        ratbagd = bytes([0x11, 0x01, FEATURE_INDEX, 0x48, 0x00, 0x03]).ljust(20, b"\0")
        device.noise = [ratbagd]
        reader = onboard(device)
        self.assertEqual(reader.active_slot(), 1)

    def test_an_error_for_another_process_is_ignored(self):
        device = FakeDevice(profile=2)
        other = bytes([0x11, 0x01, 0xFF, FEATURE_INDEX, 0x48, 0x05]).ljust(20, b"\0")
        device.noise = [other]
        self.assertEqual(onboard(device).active_slot(), 1)

    def test_a_short_or_foreign_report_is_ignored(self):
        device = FakeDevice(profile=2)
        device.noise = [b"\x02\x00\x00", b"\x01" * 8]
        self.assertEqual(onboard(device).active_slot(), 1)


class NodeTests(unittest.TestCase):
    """The node comes from the ratbagd path the daemon just confirmed."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.sys = Path(directory.name)

    def _node(self, name, hid_id):
        uevent = self.sys / name / "device" / "uevent"
        uevent.parent.mkdir(parents=True)
        uevent.write_text(f"DRIVER=logitech-hidpp-device\nHID_ID={hid_id}\nHID_NAME=x\n")

    def test_the_ratbagd_path_names_the_node(self):
        self._node("hidraw31", "0003:0000046D:0000407F")
        self.assertEqual(
            hidpp.node_for("/org/freedesktop/ratbag1/device/hidraw31", sys_root=self.sys),
            Path("/dev/hidraw31"),
        )

    def test_a_node_that_is_not_logitech_is_refused(self):
        self._node("hidraw31", "0003:00000BDA:00001100")
        with self.assertRaisesRegex(hidpp.NodeMismatch, "not a Logitech"):
            hidpp.node_for("/org/freedesktop/ratbag1/device/hidraw31", sys_root=self.sys)

    def test_a_path_that_does_not_name_a_node_is_refused(self):
        with self.assertRaisesRegex(hidpp.NodeMismatch, "does not name a hidraw node"):
            hidpp.node_for("/org/freedesktop/ratbag1/device/mouse0", sys_root=self.sys)

    def test_a_node_missing_from_sysfs_is_gone_not_a_mismatch(self):
        """ratbagd lags the kernel by about 2 s after a KVM switch, so for a
        moment it names a node the kernel has already removed."""
        with self.assertRaises(hidpp.NodeGone):
            hidpp.node_for("/org/freedesktop/ratbag1/device/hidraw31", sys_root=self.sys)

    def test_gone_and_mismatch_are_different_failures(self):
        self.assertFalse(issubclass(hidpp.NodeGone, hidpp.NodeMismatch))
        self.assertFalse(issubclass(hidpp.NodeMismatch, hidpp.NodeGone))


if __name__ == "__main__":
    unittest.main()
