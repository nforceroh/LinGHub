"""Tests for the Slot rules.

ADR-0001 says the desktop profile lives in slot 0 and whichever gaming profile
is active lives in slot 1. These tests state that rule directly, so the ADR
cannot drift from the code without a failure.
"""

import unittest

from linghub.daemon import slots
from linghub.domain.profile import Game, Profile


DESKTOP = Profile(name="desktop")
WOT = Profile(name="world-of-tanks", games=(Game("WorldOfTanks.exe"),))


class SlotForTests(unittest.TestCase):
    def test_the_desktop_profile_belongs_in_slot_0(self):
        self.assertEqual(slots.slot_for(DESKTOP), 0)

    def test_a_gaming_profile_belongs_in_slot_1(self):
        self.assertEqual(slots.slot_for(WOT), 1)

    def test_the_constants_match_the_adr(self):
        self.assertEqual(slots.DESKTOP_SLOT, 0)
        self.assertEqual(slots.GAMING_SLOT, 1)


class DriftTests(unittest.TestCase):
    """The hardware can be moved by something other than the daemon."""

    def test_no_drift_when_the_gaming_profile_is_in_slot_1(self):
        self.assertFalse(slots.drifted(WOT, 1))

    def test_drift_when_the_gaming_profile_is_elsewhere(self):
        self.assertTrue(slots.drifted(WOT, 2))

    def test_no_drift_when_the_desktop_profile_is_in_slot_0(self):
        """A desktop profile loaded into slot 0 is where it belongs."""
        self.assertFalse(slots.drifted(DESKTOP, 0))

    def test_drift_when_the_desktop_profile_is_displaced(self):
        self.assertTrue(slots.drifted(DESKTOP, 1))

    def test_an_unreadable_slot_counts_as_drift(self):
        """ratbagd reporting no active slot means we cannot claim agreement."""
        self.assertTrue(slots.drifted(WOT, None))

    def test_nothing_loaded_is_not_drift(self):
        """Before the first write there is nothing to disagree with.

        Reporting drift here would make the daemon rewrite on every tick.
        """
        self.assertFalse(slots.drifted(None, 3))
        self.assertFalse(slots.drifted(None, None))