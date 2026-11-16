"""Tests for binding encoding.

The special-action numbers here were verified against a G502 on libratbag
0.18 by setting each action and reading the mapping back, so these tests
guard against a regression in the table rather than restating it.
"""

import unittest

from linghub.domain.profile import Binding
from linghub.hardware import mapping


class SpecialActionTests(unittest.TestCase):
    def test_resolution_down_matches_observed_hardware_value(self):
        action_type, payload = mapping.encode(Binding("special", "resolution-down"))
        self.assertEqual(action_type, mapping.ACTION_SPECIAL)
        self.assertEqual(payload, 1073741834)

    def test_resolution_up_matches_observed_hardware_value(self):
        _, payload = mapping.encode(Binding("special", "resolution-up"))
        self.assertEqual(payload, 1073741833)

    def test_profile_cycle_up_matches_observed_hardware_value(self):
        _, payload = mapping.encode(Binding("special", "profile-cycle-up"))
        self.assertEqual(payload, 1073741837)

    def test_second_mode_matches_observed_hardware_value(self):
        _, payload = mapping.encode(Binding("special", "second-mode"))
        self.assertEqual(payload, 1073741841)

    def test_unknown_special_action_raises(self):
        with self.assertRaisesRegex(mapping.BindingError, "unknown special action"):
            mapping.encode(Binding("special", "not-a-thing"))


class ButtonTests(unittest.TestCase):
    def test_button_maps_to_its_number(self):
        action_type, payload = mapping.encode(Binding("button", 4))
        self.assertEqual(action_type, mapping.ACTION_BUTTON)
        self.assertEqual(payload, 4)

    def test_out_of_range_button_raises(self):
        with self.assertRaisesRegex(mapping.BindingError, "out of range"):
            mapping.encode(Binding("button", 99))


class DisabledTests(unittest.TestCase):
    def test_disabled_never_encodes_as_none(self):
        action_type, _ = mapping.encode(Binding("disabled"))
        self.assertNotEqual(action_type, mapping.ACTION_NONE)

    def test_disabled_uses_a_special_action(self):
        action_type, _ = mapping.encode(Binding("disabled"))
        self.assertEqual(action_type, mapping.ACTION_SPECIAL)


class KeyTests(unittest.TestCase):
    def test_key_resolves_from_kernel_headers(self):
        action_type, payload = mapping.encode(Binding("key", "KEY_F"))
        self.assertEqual(action_type, mapping.ACTION_KEY)
        self.assertEqual(payload, 33)

    def test_key_rejects_non_key_names(self):
        with self.assertRaisesRegex(mapping.BindingError, r"must be a KEY_\* name"):
            mapping.encode(Binding("key", "F"))

    def test_unknown_key_raises(self):
        with self.assertRaisesRegex(mapping.BindingError, "unknown key name"):
            mapping.encode(Binding("key", "KEY_NOT_A_REAL_KEY"))


class MacroTests(unittest.TestCase):
    def test_single_key_becomes_press_and_release(self):
        _, events = mapping.encode(Binding("macro", "KEY_A"))
        self.assertEqual(events, [(mapping.MACRO_KEY_PRESS, 30), (mapping.MACRO_KEY_RELEASE, 30)])

    def test_chord_encodes_press_and_release_pairs(self):
        _, events = mapping.encode(Binding("macro", "+KEY_LEFTCTRL +KEY_C -KEY_C -KEY_LEFTCTRL"))
        self.assertEqual(events, [
            (mapping.MACRO_KEY_PRESS, 29),
            (mapping.MACRO_KEY_PRESS, 46),
            (mapping.MACRO_KEY_RELEASE, 46),
            (mapping.MACRO_KEY_RELEASE, 29),
        ])

    def test_wait_token_encodes_as_wait_event(self):
        _, events = mapping.encode(Binding("macro", "KEY_A t300"))
        self.assertEqual(events[-1], (mapping.MACRO_WAIT, 300))

    def test_empty_macro_raises(self):
        with self.assertRaisesRegex(mapping.BindingError, "at least one event"):
            mapping.encode(Binding("macro", "   "))


if __name__ == "__main__":
    unittest.main()
