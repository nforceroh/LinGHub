"""Tests for the binding vocabulary the UI offers.

The important invariant: every choice the editor presents must be encodable
by the hardware path. Offering something that fails at commit time gives the
user a cryptic error from libratbag long after they made the choice.
"""

import unittest

from linghub.domain.profile import Binding
from linghub.hardware.mapping import SPECIAL_ACTIONS, encode
from linghub.ui.binding_labels import (
    BUTTON_CHOICES,
    COMMON_KEYS,
    SPECIAL_CHOICES,
    describe_binding,
    describe_chord,
)


class VocabularyTests(unittest.TestCase):
    def test_every_key_choice_encodes(self):
        for name, _label in COMMON_KEYS:
            with self.subTest(key=name):
                encode(Binding("key", name))

    def test_every_special_choice_encodes(self):
        for name, _label in SPECIAL_CHOICES:
            with self.subTest(special=name):
                encode(Binding("special", name))

    def test_every_button_choice_encodes(self):
        for number, _label in BUTTON_CHOICES:
            with self.subTest(button=number):
                encode(Binding("button", number))

    def test_disabled_encodes(self):
        encode(Binding("disabled", None))

    def test_second_mode_is_not_offered(self):
        """libratbag rejects it on the G502 (issue #1798)."""
        offered = {name for name, _label in SPECIAL_CHOICES}
        self.assertNotIn("second-mode", offered)

    def test_choices_exist_in_the_encoder(self):
        offered = {name for name, _label in SPECIAL_CHOICES}
        self.assertTrue(offered <= set(SPECIAL_ACTIONS))

    def test_labels_are_unique(self):
        labels = [label for _value, label in SPECIAL_CHOICES]
        self.assertEqual(len(labels), len(set(labels)))


class DescribeTests(unittest.TestCase):
    def test_key_uses_a_friendly_name(self):
        self.assertEqual(describe_binding("key", "KEY_SPACE"), "Space")

    def test_unlisted_key_falls_back_to_the_name_without_prefix(self):
        self.assertEqual(describe_binding("key", "KEY_KPENTER"), "KPENTER")

    def test_special_uses_a_friendly_name(self):
        self.assertEqual(describe_binding("special", "resolution-up"), "DPI up")

    def test_button_uses_a_friendly_name(self):
        self.assertEqual(describe_binding("button", 4), "Back")

    def test_disabled_is_nothing(self):
        self.assertEqual(describe_binding("disabled", None), "Nothing")

    def test_empty_kind_is_nothing(self):
        self.assertEqual(describe_binding("", None), "Nothing")

    def test_unknown_special_shows_the_raw_name(self):
        self.assertEqual(describe_binding("special", "made-up"), "made-up")

    def test_unknown_type_degrades_gracefully(self):
        self.assertEqual(describe_binding("weird", "x"), "weird: x")


class ChordTests(unittest.TestCase):
    def test_single_key_needs_no_modifiers(self):
        self.assertEqual(describe_chord(["KEY_F"]), "KEY_F")

    def test_chord_presses_modifiers_then_releases_in_reverse(self):
        spec = describe_chord(["KEY_LEFTCTRL", "KEY_LEFTSHIFT", "KEY_C"])
        self.assertEqual(
            spec, "+KEY_LEFTCTRL +KEY_LEFTSHIFT +KEY_C -KEY_C -KEY_LEFTSHIFT -KEY_LEFTCTRL"
        )

    def test_chord_encodes(self):
        """The generated spec must be accepted by the macro encoder."""
        spec = describe_chord(["KEY_LEFTCTRL", "KEY_C"])
        encode(Binding("macro", spec))

    def test_empty_chord_is_empty(self):
        self.assertEqual(describe_chord([]), "")


if __name__ == "__main__":
    unittest.main()
