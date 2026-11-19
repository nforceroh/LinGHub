"""Tests for deciding the active slot from the mouse and ratbagd (#2).

The mouse's answer wins. What each kind of failed read means is the point of
these tests: only a gone node is a lost mouse; a silent or erroring mouse
leaves the slot unknown; a refused node falls back to ratbagd.
"""

import asyncio
import errno
import unittest

from linghub.hardware import hidpp
from linghub.hardware.active_slot import ActiveSlotReader, NoReading, Reason, SlotUnknown


class FakeMouse:
    def __init__(self, slot=1):
        self.slot = slot
        self.error: Exception | None = None

    def active_slot(self) -> int:
        if self.error is not None:
            raise self.error
        return self.slot


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.believed = 1
        self.mouse = FakeMouse(slot=1)

    async def _believed(self):
        return self.believed

    def _reader(self, mouse="default"):
        return ActiveSlotReader(self._believed, self.mouse if mouse == "default" else mouse)

    def read(self, reader):
        return asyncio.run(reader.read())

    def test_the_mouse_wins_over_ratbagd(self):
        """The bug: ratbagd said 1 while the mouse sat on 0."""
        self.believed, self.mouse.slot = 1, 0
        with self.assertLogs("linghub.hardware.active_slot", "INFO"):
            self.assertEqual(self.read(self._reader()), 0)

    def test_a_disagreement_is_logged_once_while_it_lasts(self):
        reader = self._reader()
        self.believed, self.mouse.slot = 2, 1
        with self.assertLogs("linghub.hardware.active_slot", "INFO") as logs:
            self.read(reader)
            self.read(reader)
            self.read(reader)
        disagreements = [m for m in logs.output if "ratbagd says slot 2" in m]
        self.assertEqual(len(disagreements), 1, logs.output)
        self.assertIn("the mouse says slot 1", disagreements[0])

    def test_a_new_disagreement_is_logged_again(self):
        reader = self._reader()
        with self.assertLogs("linghub.hardware.active_slot", "INFO") as logs:
            self.believed, self.mouse.slot = 2, 1
            self.read(reader)
            self.believed = 1           # they agree again
            self.read(reader)
            self.believed = 2           # and disagree again
            self.read(reader)
        self.assertEqual(sum("ratbagd says" in m for m in logs.output), 2, logs.output)

    def test_agreement_logs_nothing(self):
        with self.assertNoLogs("linghub.hardware.active_slot", "INFO"):
            self.assertEqual(self.read(self._reader()), 1)

    def test_a_silent_mouse_leaves_the_slot_unknown(self):
        self.mouse.error = hidpp.NoReply("no reply")
        with self.assertRaises(SlotUnknown):
            self.read(self._reader())

    def test_an_erroring_mouse_leaves_the_slot_unknown(self):
        self.mouse.error = hidpp.HidppError("error 0x05")
        with self.assertRaises(SlotUnknown):
            self.read(self._reader())

    def test_unknown_is_not_a_lost_mouse(self):
        """The daemon reconnects on RuntimeError and OSError; this is neither."""
        self.assertFalse(issubclass(SlotUnknown, (RuntimeError, OSError)))

    def test_a_gone_node_is_a_lost_mouse(self):
        for error in (FileNotFoundError(errno.ENOENT, "gone"),
                      OSError(errno.ENODEV, "no such device")):
            with self.subTest(error=error):
                self.mouse.error = error
                with self.assertRaises(OSError) as raised:
                    self.read(self._reader())
                self.assertNotIsInstance(raised.exception, PermissionError)

    def test_a_refused_node_falls_back_to_ratbagd(self):
        self.believed = 2
        self.mouse.error = PermissionError(errno.EACCES, "denied")
        with self.assertLogs("linghub.hardware.active_slot", "WARNING"):
            self.assertEqual(self.read(self._reader()), 2)

    def test_a_refused_node_warns_once_not_every_check(self):
        reader = self._reader()
        self.mouse.error = PermissionError(errno.EACCES, "denied")
        with self.assertLogs("linghub.hardware.active_slot", "WARNING") as logs:
            for _ in range(5):
                self.read(reader)
        self.assertEqual(len(logs.output), 1, logs.output)

    def test_access_coming_back_rearms_the_warning(self):
        reader = self._reader()
        with self.assertLogs("linghub.hardware.active_slot", "WARNING") as logs:
            self.mouse.error = PermissionError(errno.EACCES, "denied")
            self.read(reader)
            self.mouse.error = None
            self.read(reader)
            self.mouse.error = PermissionError(errno.EACCES, "denied")
            self.read(reader)
        self.assertEqual(sum("permission" in m.lower() for m in logs.output), 2, logs.output)

    def test_host_mode_leaves_the_slot_unknown_and_warns_once(self):
        reader = self._reader()
        self.mouse.error = hidpp.HostMode("host mode")
        with self.assertLogs("linghub.hardware.active_slot", "WARNING") as logs:
            for _ in range(3):
                with self.assertRaises(SlotUnknown):
                    self.read(reader)
        self.assertEqual(len(logs.output), 1, logs.output)

    def test_without_a_mouse_reader_ratbagd_answers(self):
        """The node could not be confirmed as the mouse: ratbagd is all we have."""
        self.believed = 2
        self.assertEqual(self.read(self._reader(mouse=None)), 2)



class MouseForTests(unittest.TestCase):
    """Building the mouse reader from the device the daemon just confirmed."""

    def setUp(self):
        import tempfile
        from pathlib import Path

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.sys = Path(directory.name)

    def _node(self, name, hid_id):
        uevent = self.sys / name / "device" / "uevent"
        uevent.parent.mkdir(parents=True)
        uevent.write_text(f"HID_ID={hid_id}\n")

    def test_a_logitech_node_gets_a_mouse_reader_on_that_node(self):
        from pathlib import Path
        from linghub.hardware.mouse import mouse_for

        self._node("hidraw31", "0003:0000046D:0000407F")
        opened = []
        mouse = mouse_for(
            "/org/freedesktop/ratbag1/device/hidraw31",
            sys_root=self.sys, open_node=lambda path: opened.append(path),
        )
        self.assertIsNotNone(mouse)
        try:
            mouse.active_slot()
        except Exception:  # noqa: BLE001 - the fake opener returns nothing usable
            pass
        self.assertEqual(opened, [Path("/dev/hidraw31")])

    def test_a_gone_node_means_the_mouse_is_still_missing(self):
        """Seen live: the kernel had removed hidraw31 but ratbagd still listed
        it, so the daemon "reconnected" to a mouse on the other machine,
        logged an error, and announced it back after 0 s."""
        from linghub.hardware.mouse import mouse_for
        from linghub.hardware.failures import MouseAbsent
        from linghub.hardware.ratbag import NOT_FOUND

        with self.assertNoLogs("linghub.hardware.active_slot", "ERROR"):
            with self.assertRaises(MouseAbsent) as raised:
                mouse_for("/org/freedesktop/ratbag1/device/hidraw31", sys_root=self.sys)
        self.assertEqual(str(raised.exception), NOT_FOUND)

    def test_an_unconfirmed_node_falls_back_to_ratbagd_loudly(self):
        from linghub.hardware.mouse import mouse_for

        self._node("hidraw31", "0003:00000BDA:00001100")
        with self.assertLogs("linghub.hardware.mouse", "ERROR"):
            mouse = mouse_for("/org/freedesktop/ratbag1/device/hidraw31", sys_root=self.sys)
        self.assertIsNone(mouse)


if __name__ == "__main__":
    unittest.main()


class ReadingsTests(unittest.TestCase):
    """Both answers, side by side, for `linghub status` (#5).

    Unlike read(), readings() never decides for the caller: it reports what
    each source said and why the mouse couldn't answer, and logs nothing.
    """

    def setUp(self):
        self.believed = 1
        self.mouse = FakeMouse(slot=1)

    async def _believed(self):
        return self.believed

    def _readings(self, mouse="default"):
        reader = ActiveSlotReader(self._believed, self.mouse if mouse == "default" else mouse)
        return asyncio.run(reader.readings())

    def test_both_answers_when_the_mouse_answers(self):
        self.believed, self.mouse.slot = 2, 0
        readings = self._readings()
        self.assertEqual((readings.answer, readings.believed), (0, 2))

    def test_no_answer(self):
        self.mouse.error = hidpp.NoReply("no reply")
        readings = self._readings()
        self.assertEqual(readings.believed, 1)
        self.assertEqual(readings.answer, NoReading(Reason.NO_ANSWER, "no reply"))

    def test_a_hidpp_error_is_no_answer(self):
        self.mouse.error = hidpp.HidppError("error 0x05")
        self.assertEqual(self._readings().answer.reason, Reason.NO_ANSWER)

    def test_host_mode(self):
        self.mouse.error = hidpp.HostMode("host mode")
        self.assertEqual(self._readings().answer.reason, Reason.HOST_MODE)

    def test_no_permission(self):
        self.mouse.error = PermissionError(errno.EACCES, "denied")
        readings = self._readings()
        self.assertEqual(readings.believed, 1)
        self.assertEqual(readings.answer.reason, Reason.NO_PERMISSION)

    def test_an_unconfirmed_node(self):
        self.assertEqual(self._readings(mouse=None).answer.reason, Reason.UNCONFIRMED_NODE)

    def test_a_gone_node_still_propagates(self):
        self.mouse.error = FileNotFoundError(errno.ENOENT, "gone")
        with self.assertRaises(OSError):
            self._readings()

    def test_readings_log_nothing(self):
        self.believed, self.mouse.slot = 2, 0
        with self.assertNoLogs("linghub.hardware.active_slot", "DEBUG"):
            self._readings()
