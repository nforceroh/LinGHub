"""Tests for the hidraw diagnostic.

The failure this guards against is real: a stale Wine process holding a
deleted /dev/hidraw node stops the device reappearing, and the old code
reported only "no G502 found".
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from linghub.hardware import diagnose


class FindHoldersTests(unittest.TestCase):
    def test_returns_empty_when_no_proc_entries(self):
        with mock.patch.object(diagnose, "PROC", Path("/nonexistent")):
            self.assertEqual(diagnose.find_deleted_hidraw_holders(), [])

    def test_detects_a_deleted_hidraw_fd(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = Path(tmp)
            pid_dir = proc / "1234"
            fd_dir = pid_dir / "fd"
            fd_dir.mkdir(parents=True)
            (pid_dir / "cmdline").write_bytes(b"wine\x00WorldOfTanks.exe\x00")
            # A symlink whose target contains "hidraw" and "deleted".
            os.symlink("/dev/hidraw12 (deleted)", fd_dir / "7")

            with mock.patch.object(diagnose, "PROC", proc):
                holders = diagnose.find_deleted_hidraw_holders()

        self.assertEqual(len(holders), 1)
        self.assertEqual(holders[0].pid, 1234)
        self.assertEqual(holders[0].node, "/dev/hidraw12")
        self.assertIn("WorldOfTanks.exe", holders[0].command)

    def test_ignores_live_hidraw_fd(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = Path(tmp)
            pid_dir = proc / "1234"
            fd_dir = pid_dir / "fd"
            fd_dir.mkdir(parents=True)
            (pid_dir / "cmdline").write_bytes(b"game\x00")
            os.symlink("/dev/hidraw12", fd_dir / "7")

            with mock.patch.object(diagnose, "PROC", proc):
                holders = diagnose.find_deleted_hidraw_holders()

        self.assertEqual(holders, [])

    def test_ignores_unrelated_deleted_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = Path(tmp)
            pid_dir = proc / "1234"
            fd_dir = pid_dir / "fd"
            fd_dir.mkdir(parents=True)
            (pid_dir / "cmdline").write_bytes(b"game\x00")
            os.symlink("/tmp/somefile (deleted)", fd_dir / "7")

            with mock.patch.object(diagnose, "PROC", proc):
                holders = diagnose.find_deleted_hidraw_holders()

        self.assertEqual(holders, [])


class DescribeFailureTests(unittest.TestCase):
    def test_names_the_offending_process(self):
        holder = diagnose.HidrawHolder(pid=42, command="wine WorldOfTanks.exe", node="/dev/hidraw12")
        with mock.patch.object(diagnose, "find_deleted_hidraw_holders", return_value=[holder]):
            message = diagnose.describe_failure()

        self.assertIn("pid 42", message)
        self.assertIn("WorldOfTanks.exe", message)
        self.assertIn("/dev/hidraw12", message)
        self.assertIn("replug", message)

    def test_falls_back_when_no_holders(self):
        with mock.patch.object(diagnose, "find_deleted_hidraw_holders", return_value=[]):
            message = diagnose.describe_failure()

        self.assertIn("no stale hidraw holders", message)
        self.assertIn("ratbagd is running", message)


if __name__ == "__main__":
    unittest.main()
