"""Tests for the absence rules, tested directly instead of through log counts.

The rules from #4: warn once per absence, say how long the mouse was away
when it comes back, and no "back" line for a mouse that was never there.
"""

import logging
import unittest

from linghub.daemon.absence import Absence


class Clock:
    def __init__(self, now: float = 1000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


class LostTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.absence = Absence(self.clock)

    def test_losing_the_mouse_is_said_at_once(self):
        report = self.absence.lost("lost the device: gone")
        self.assertEqual(report.message, "lost the device: gone")
        self.assertEqual(report.level, logging.WARNING)

    def test_losing_the_mouse_starts_the_absence(self):
        self.assertFalse(self.absence.ongoing)
        self.absence.lost("lost the device: gone")
        self.assertTrue(self.absence.ongoing)

    def test_losing_it_twice_does_not_restart_the_clock(self):
        self.absence.lost("lost the device: gone")
        self.clock.now += 60
        self.absence.lost("lost the device: gone again")
        self.clock.now += 60
        self.assertEqual(self.absence.found().message, "device is back after 2m 0s")


class SearchFailedTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.absence = Absence(self.clock)

    def test_the_first_failed_search_is_said(self):
        report = self.absence.search_failed("no G502 found")
        self.assertEqual(report.message, "no G502 found")
        self.assertEqual(report.level, logging.WARNING)

    def test_every_later_failed_search_is_debug(self):
        self.absence.search_failed("no G502 found")
        for _ in range(5):
            report = self.absence.search_failed("no G502 found")
            self.assertEqual(report.level, logging.DEBUG)

    def test_a_misconfiguration_is_an_error_the_first_time_only(self):
        report = self.absence.search_failed("two G502s", level=logging.ERROR)
        self.assertEqual(report.level, logging.ERROR)
        self.assertEqual(
            self.absence.search_failed("two G502s", level=logging.ERROR).level,
            logging.DEBUG,
        )

    def test_a_failed_search_starts_the_absence(self):
        self.absence.search_failed("no G502 found")
        self.assertTrue(self.absence.ongoing)


class FoundTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.absence = Absence(self.clock)

    def test_a_mouse_that_was_away_says_how_long(self):
        self.absence.lost("lost the device: gone")
        self.clock.now += 192
        report = self.absence.found()
        self.assertEqual(report.message, "device is back after 3m 12s")
        self.assertEqual(report.level, logging.INFO)

    def test_a_mouse_missing_at_startup_has_no_back_line(self):
        """The connector's own "found ..." line is the first thing seen."""
        self.absence.search_failed("no G502 found")
        self.assertIsNone(self.absence.found().message)

    def test_a_mouse_that_never_left_has_nothing_to_say(self):
        self.assertIsNone(self.absence.found().message)

    def test_finding_it_ends_the_absence(self):
        self.absence.lost("lost the device: gone")
        self.absence.found()
        self.assertFalse(self.absence.ongoing)

    def test_a_second_absence_warns_again(self):
        self.absence.lost("lost the device: gone")
        self.absence.found()
        self.absence.lost("lost the device: gone again")
        self.assertEqual(
            self.absence.search_failed("no G502 found").level, logging.WARNING
        )

    def test_a_second_absence_says_how_long_again(self):
        self.absence.lost("lost the device: gone")
        self.absence.found()
        self.absence.lost("lost the device: gone again")
        self.clock.now += 45
        self.assertEqual(self.absence.found().message, "device is back after 45s")


class DurationTests(unittest.TestCase):
    def test_seconds_minutes_and_hours(self):
        from linghub.daemon.absence import _duration

        self.assertEqual(_duration(45), "45s")
        self.assertEqual(_duration(192), "3m 12s")
        self.assertEqual(_duration(3720), "1h 2m")


if __name__ == "__main__":
    unittest.main()
