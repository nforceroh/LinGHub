"""Edits held until Save, and thrown away by Discard.

The window used to commit each kind of edit differently: a binding went to the
daemon the moment the editor's Apply was pressed, while DPI and lighting each
had their own Save. That made "discard my changes" impossible to offer
honestly. These tests pin the rule that replaced it.
"""

import unittest

from linghub.ui.pending_edits import PendingEdits, PendingEditsFor


class DirtyTests(unittest.TestCase):
    def test_a_new_profile_has_nothing_pending(self):
        self.assertFalse(PendingEdits(profile="desktop").dirty)

    def test_a_binding_makes_it_dirty(self):
        edits = PendingEdits(profile="desktop")
        edits.set_binding(2, "key", "KEY_X")
        self.assertTrue(edits.dirty)

    def test_resolutions_make_it_dirty(self):
        edits = PendingEdits(profile="desktop")
        edits.set_resolutions([(800, True, False)], 1000)
        self.assertTrue(edits.dirty)

    def test_lighting_makes_it_dirty(self):
        edits = PendingEdits(profile="desktop")
        edits.set_leds("breathing", 255, 8000, (1, 2, 3))
        self.assertTrue(edits.dirty)

    def test_clear_forgets_everything(self):
        edits = PendingEdits(profile="desktop")
        edits.set_binding(2, "key", "KEY_X")
        edits.set_resolutions([(800, True, False)], 1000)
        edits.set_leds("breathing", 255, 8000, (1, 2, 3))
        edits.clear()
        self.assertFalse(edits.dirty)


class BindingTests(unittest.TestCase):
    def test_a_binding_is_recorded_by_index(self):
        edits = PendingEdits(profile="desktop")
        edits.set_binding(2, "key", "KEY_X")
        self.assertEqual(edits.bindings[2].kind, "key")
        self.assertEqual(edits.bindings[2].value, "KEY_X")

    def test_a_later_binding_replaces_the_earlier_one(self):
        """Editing the same button twice must not queue two writes."""
        edits = PendingEdits(profile="desktop")
        edits.set_binding(2, "key", "KEY_X")
        edits.set_binding(2, "key", "KEY_F")
        self.assertEqual(len(edits.bindings), 1)
        self.assertEqual(edits.bindings[2].value, "KEY_F")

    def test_disabled_is_a_binding_too(self):
        """Unassigning is an edit, not the absence of one."""
        edits = PendingEdits(profile="desktop")
        edits.set_binding(2, "disabled")
        self.assertTrue(edits.dirty)
        self.assertEqual(edits.bindings[2].kind, "disabled")


class ResolutionTests(unittest.TestCase):
    def test_slots_and_rate_are_recorded_together(self):
        edits = PendingEdits(profile="desktop")
        edits.set_resolutions([(400, False, False), (800, True, False)], 500)
        self.assertEqual(edits.resolutions, [(400, False, False), (800, True, False)])
        self.assertEqual(edits.report_rate, 500)

    def test_a_zero_rate_is_not_recorded(self):
        """0 means the panel had no rate to offer, not "set it to zero"."""
        edits = PendingEdits(profile="desktop")
        edits.set_resolutions([(800, True, False)], 0)
        self.assertIsNone(edits.report_rate)
        self.assertTrue(edits.dirty, "the slots are still pending")


class LightingTests(unittest.TestCase):
    def test_the_four_values_are_recorded(self):
        edits = PendingEdits(profile="desktop")
        edits.set_leds("breathing", 200, 5000, (10, 20, 30))
        self.assertEqual(edits.leds["mode"], "breathing")
        self.assertEqual(edits.leds["brightness"], 200)
        self.assertEqual(edits.leds["duration"], 5000)
        self.assertEqual(edits.leds["color"], (10, 20, 30))


class PerProfileTests(unittest.TestCase):
    def test_edits_are_kept_for_the_profile_they_belong_to(self):
        pending = PendingEditsFor()
        pending.for_profile("desktop").set_binding(2, "key", "KEY_X")
        self.assertEqual(pending.current.profile, "desktop")

    def test_asking_for_a_different_profile_starts_empty(self):
        """Switching profiles is refused while dirty, so this only happens
        after a save or a discard."""
        pending = PendingEditsFor()
        pending.for_profile("desktop").set_binding(2, "key", "KEY_X")
        other = pending.for_profile("world-of-tanks")
        self.assertFalse(other.dirty)
        self.assertEqual(other.profile, "world-of-tanks")

    def test_dirty_is_false_before_any_profile_is_asked_for(self):
        self.assertFalse(PendingEditsFor().dirty)

    def test_clear_empties_the_current_profile(self):
        pending = PendingEditsFor()
        pending.for_profile("desktop").set_binding(2, "key", "KEY_X")
        pending.clear()
        self.assertFalse(pending.dirty)


if __name__ == "__main__":
    unittest.main()
