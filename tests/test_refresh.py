"""Tests for the refresh guard.

The window refreshes from the poll, from daemon signals, and after every
write. The guard is what stops two of those from running at once and applying
an older view last.
"""

import unittest

from linghub.ui.refresh import RefreshGuard


class BeginTests(unittest.TestCase):
    def test_the_first_begin_claims_the_slot(self):
        guard = RefreshGuard()
        self.assertTrue(guard.begin())
        self.assertTrue(guard.running)

    def test_a_second_begin_is_refused(self):
        guard = RefreshGuard()
        guard.begin()
        self.assertFalse(guard.begin())

    def test_a_refused_begin_is_remembered(self):
        guard = RefreshGuard()
        guard.begin()
        guard.begin()
        self.assertTrue(guard.end(), "the pending request was lost")


class EndTests(unittest.TestCase):
    def test_end_with_nothing_pending_reports_no_repeat(self):
        guard = RefreshGuard()
        guard.begin()
        self.assertFalse(guard.end())
        self.assertFalse(guard.running)

    def test_end_with_a_pending_request_reports_a_repeat(self):
        guard = RefreshGuard()
        guard.begin()
        guard.begin()
        self.assertTrue(guard.end())

    def test_the_pending_flag_is_cleared_by_end(self):
        guard = RefreshGuard()
        guard.begin()
        guard.begin()
        guard.end()
        guard.begin()
        self.assertFalse(guard.end(), "a stale pending flag caused a repeat")

    def test_many_requests_collapse_into_one_repeat(self):
        """A signal storm must not queue a refresh per signal."""
        guard = RefreshGuard()
        guard.begin()
        for _ in range(10):
            guard.begin()
        self.assertTrue(guard.end())
        guard.begin()
        self.assertFalse(guard.end(), "ten requests produced more than one repeat")


if __name__ == "__main__":
    unittest.main()
