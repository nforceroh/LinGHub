"""Tests for config change detection."""

import os
import tempfile
import time
import unittest
from pathlib import Path

from linghub.daemon.watcher import ConfigWatcher


class WatcherTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "config.json"
        self.path.write_text("{}", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_first_check_reports_change(self):
        self.assertTrue(ConfigWatcher(self.path).changed())

    def test_unchanged_file_reports_no_change(self):
        watcher = ConfigWatcher(self.path)
        watcher.changed()
        self.assertFalse(watcher.changed())

    def test_rewrite_reports_change(self):
        watcher = ConfigWatcher(self.path)
        watcher.changed()
        self.path.write_text('{"version": 1}', encoding="utf-8")
        self.assertTrue(watcher.changed())

    def test_same_size_rewrite_is_detected(self):
        """A same-length edit must not be missed.

        This is why the signature includes mtime_ns rather than comparing
        only size, and why it compares for inequality rather than "newer".
        """
        watcher = ConfigWatcher(self.path)
        watcher.changed()
        self.path.write_text("{ }", encoding="utf-8")  # same length as "{}" plus space
        self.assertTrue(watcher.changed())

    def test_missing_file_reports_change(self):
        watcher = ConfigWatcher(self.path)
        watcher.changed()
        self.path.unlink()
        self.assertTrue(watcher.changed())

    def test_reset_forces_next_check_to_report_change(self):
        watcher = ConfigWatcher(self.path)
        watcher.changed()
        watcher.reset()
        self.assertTrue(watcher.changed())

    def test_recreated_file_is_detected_by_inode(self):
        watcher = ConfigWatcher(self.path)
        watcher.changed()
        replacement = Path(self._tmp.name) / "new.json"
        replacement.write_text("{}", encoding="utf-8")
        os.replace(replacement, self.path)
        self.assertTrue(watcher.changed())


if __name__ == "__main__":
    unittest.main()
