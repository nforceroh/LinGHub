"""Tests for `linghub --version`: this process's version and the daemon's.

The formatting is separate from the D-Bus read, so it is tested without a bus.
"""

import subprocess
import sys
import unittest
from pathlib import Path

from linghub import version
from linghub.cli import format_version
from linghub.version import DAEMON_NOT_RUNNING

REPO = Path(__file__).resolve().parent.parent


class FormatVersionTests(unittest.TestCase):
    def test_a_matching_daemon_is_shown_without_a_note(self):
        self.assertEqual(
            format_version("0.1.0", "0.1.0"),
            "LinGHub 0.1.0\nDaemon  0.1.0",
        )

    def test_a_different_daemon_says_to_restart_it(self):
        self.assertEqual(
            format_version("0.1.0+1.gabc1234", "0.1.0"),
            "LinGHub 0.1.0+1.gabc1234\nDaemon  0.1.0\n"
            "Daemon is running 0.1.0; restart it",
        )

    def test_an_old_daemon_predates_version_reporting(self):
        self.assertEqual(
            format_version("0.1.0", version.PREDATES_REPORTING),
            "LinGHub 0.1.0\nDaemon  unknown\n"
            "Daemon predates version reporting; restart it",
        )

    def test_no_daemon_is_not_a_mismatch(self):
        self.assertEqual(
            format_version("0.1.0", DAEMON_NOT_RUNNING),
            "LinGHub 0.1.0\nDaemon  not running",
        )


class VersionFlagTests(unittest.TestCase):
    def test_the_flag_needs_no_subcommand_and_prints_this_version(self):
        """Run for real: argparse otherwise demands a subcommand."""
        result = subprocess.run(
            [sys.executable, "-m", "linghub.cli", "--version"],
            capture_output=True, text=True, timeout=30, cwd=REPO,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(
            result.stdout.startswith(f"LinGHub {version.current()}\n"), result.stdout
        )


if __name__ == "__main__":
    unittest.main()
