"""Tests for the status command's formatting.

`linghub status` asks the running daemon what it is doing, so the formatting is
kept separate from the D-Bus call and can be tested without a bus.
"""

import unittest

from linghub.cli import format_status


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
