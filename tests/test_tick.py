"""Tests for the tick's decision.

The override's lifetime is the code with the bug history: an override that
never cleared left a gaming profile on the mouse with no game running. It is
pure, so it is tested here directly — no daemon, no asyncio, no patched
module global.
"""

import unittest

from linghub.daemon.tick import OverrideEnded, decide


class OverrideLifetimeTests(unittest.TestCase):
    def test_an_override_survives_while_the_same_game_runs(self):
        """Picking a profile mid-game must not be undone by the next tick."""
        decision = decide("wot", "wot", "wot")
        self.assertEqual(decision.override, "wot")
        self.assertIsNone(decision.detected)
        self.assertIsNone(decision.exited)
        self.assertIsNone(decision.ended, "an unchanged override has no reason")

    def test_an_override_is_cleared_when_the_game_changes(self):
        decision = decide("wot", "star-citizen", "wot")
        self.assertIsNone(decision.override)
        self.assertEqual(decision.detected, "star-citizen")
        self.assertIs(decision.ended, OverrideEnded.GAME_CHANGED)

    def test_an_override_is_cleared_when_the_game_exits(self):
        decision = decide("wot", None, "wot")
        self.assertIsNone(decision.override)
        self.assertEqual(decision.exited, "wot")
        self.assertIs(decision.ended, OverrideEnded.GAME_CHANGED)

    def test_an_override_with_no_game_running_is_cleared(self):
        """The bug this rule exists for: a stuck override with nothing running."""
        decision = decide(None, None, "wot")
        self.assertIsNone(decision.override)
        self.assertIs(decision.ended, OverrideEnded.NO_GAME)

    def test_an_override_survives_a_tick_that_detects_nothing_new(self):
        decision = decide(None, None, None)
        self.assertIsNone(decision.override)
        self.assertIsNone(decision.ended)

    def test_no_reason_when_there_was_no_override_to_clear(self):
        """A game starting with no override is not a clearing."""
        decision = decide(None, "wot", None)
        self.assertEqual(decision.detected, "wot")
        self.assertIsNone(decision.ended)


class GameEventTests(unittest.TestCase):
    def test_a_game_starting_is_announced(self):
        decision = decide(None, "wot", None)
        self.assertEqual(decision.detected, "wot")
        self.assertIsNone(decision.exited)

    def test_a_game_stopping_is_announced(self):
        decision = decide("wot", None, None)
        self.assertEqual(decision.exited, "wot")
        self.assertIsNone(decision.detected)

    def test_a_game_swapping_announces_only_the_new_one(self):
        """One event per tick: the exit of the old game is implied."""
        decision = decide("wot", "star-citizen", None)
        self.assertEqual(decision.detected, "star-citizen")
        self.assertIsNone(decision.exited)

    def test_no_change_announces_nothing(self):
        decision = decide("wot", "wot", None)
        self.assertIsNone(decision.detected)
        self.assertIsNone(decision.exited)

    def test_the_first_detection_announces_the_game(self):
        decision = decide(None, "wot", None)
        self.assertEqual(decision.detected, "wot")


if __name__ == "__main__":
    unittest.main()
