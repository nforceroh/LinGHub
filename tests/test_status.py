"""Tests for the status command's formatting.

`linghub status` asks the running daemon what it is doing, so the formatting is
kept separate from the D-Bus call and can be tested without a bus.
"""

import unittest

from linghub.cli import format_status
from linghub.hardware.active_slot import Reason


class FormatStatusTests(unittest.TestCase):
    def _format(self, **kwargs):
        defaults = dict(
            active="desktop",
            detected=None,
            desktop="desktop",
            profiles=("desktop", "world-of-tanks"),
        )
        defaults.update(kwargs)
        return format_status(**defaults)

    def test_reports_the_active_profile(self):
        self.assertIn("desktop", self._format())

    def test_reports_no_game(self):
        self.assertIn("no game", self._format(detected=None).lower())

    def test_reports_the_detected_game(self):
        self.assertIn("world-of-tanks", self._format(detected="world-of-tanks"))

    def test_reports_the_desktop_profile(self):
        self.assertIn("desktop", self._format(desktop="my-desktop"))

    def test_reports_the_profile_count(self):
        self.assertIn("2", self._format())

    def test_handles_an_unknown_active_profile(self):
        self.assertIn("unknown", self._format(active="").lower())


if __name__ == "__main__":
    unittest.main()


class FormatMouseTests(unittest.TestCase):
    """The mouse section of `linghub status`, as the mouse itself reports it (#5)."""

    NAMES = {0: "desktop", 1: "world-of-tanks"}

    def _found(self, answer, believed, names=None):
        from linghub.cli import MouseReport, format_mouse
        from linghub.hardware.active_slot import SlotReadings

        report = MouseReport(
            name="Logitech G502", node="/dev/hidraw49",
            readings=SlotReadings(answer=answer, believed=believed),
        )
        return format_mouse(report, self.NAMES if names is None else names)

    def _no_reading(self, reason, believed, names=None):
        from linghub.hardware.active_slot import NoReading

        return self._found(NoReading(reason), believed, names)

    def test_agreement(self):
        self.assertEqual(
            self._found(1, 1),
            "Mouse          : Logitech G502 on /dev/hidraw49\n"
            "Active slot    : 1 (world-of-tanks)",
        )

    def test_disagreement_shows_ratbagds_belief(self):
        self.assertIn("Active slot    : 0 (desktop) · ratbagd says 2", self._found(0, 2))

    def test_no_answer(self):
        self.assertIn(
            "Active slot    : unknown (the mouse did not answer; asleep?) · ratbagd says 1",
            self._no_reading(Reason.NO_ANSWER, 1),
        )

    def test_host_mode(self):
        self.assertIn(
            "Active slot    : none (host mode: another tool controls the mouse)",
            self._no_reading(Reason.HOST_MODE, 1),
        )

    def test_no_permission_shows_ratbagds_answer_and_says_so(self):
        self.assertIn(
            "Active slot    : 1 (world-of-tanks) · ratbagd's answer; no permission to read the mouse",
            self._no_reading(Reason.NO_PERMISSION, 1),
        )

    def test_an_unconfirmed_node_shows_ratbagds_answer_and_says_so(self):
        self.assertIn(
            "· ratbagd's answer; the device node could not be confirmed",
            self._no_reading(Reason.UNCONFIRMED_NODE, 1),
        )

    def test_an_unnamed_slot_has_no_brackets(self):
        """With the daemon down, only slot 0 has a name (from the config)."""
        self.assertIn("Active slot    : 1", self._found(1, 1, names={0: "desktop"}))
        self.assertNotIn("(", self._found(1, 1, names={0: "desktop"}).splitlines()[1])

    def test_not_found_without_holders(self):
        from linghub.cli import MouseReport, format_mouse

        self.assertEqual(
            format_mouse(MouseReport(absent=True), self.NAMES),
            "Mouse          : not found (KVM, unplugged or asleep)",
        )

    def test_not_found_lists_holders_as_a_lead(self):
        from linghub.cli import MouseReport, format_mouse
        from linghub.hardware.diagnose import HidrawHolder

        holder = HidrawHolder(pid=235448, command="winedevice.exe", node="/dev/hidraw15")
        text = format_mouse(MouseReport(absent=True, holders=(holder,)), self.NAMES)
        self.assertIn("a possible lead, often harmless", text)
        self.assertIn("pid 235448 winedevice.exe (/dev/hidraw15)", text)
        self.assertNotIn("kill", text.lower())

    def test_a_misconfiguration_shows_its_message(self):
        from linghub.cli import MouseReport, format_mouse

        text = format_mouse(
            MouseReport(misconfigured="multiple G502 devices found, so LinGHub cannot choose safely; unplug all but one"),
            self.NAMES,
        )
        self.assertTrue(text.startswith("Mouse          : multiple G502 devices found"), text)


class SlotNamesTests(unittest.TestCase):
    """Which profile each slot holds, as far as `status` can know (#5)."""

    def test_with_the_daemon_running_slot_1_is_what_it_last_loaded(self):
        from linghub.cli import slot_names

        self.assertEqual(
            slot_names(desktop="desktop", loaded="world-of-tanks"),
            {0: "desktop", 1: "world-of-tanks"},
        )

    def test_with_the_desktop_loaded_slot_1_is_unknown(self):
        from linghub.cli import slot_names

        self.assertEqual(slot_names(desktop="desktop", loaded="desktop"), {0: "desktop"})

    def test_with_the_daemon_down_only_slot_0_is_named(self):
        from linghub.cli import slot_names

        self.assertEqual(slot_names(desktop="desktop", loaded=None), {0: "desktop"})
