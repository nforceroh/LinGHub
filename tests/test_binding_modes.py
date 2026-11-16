"""Tests for the binding editor's mode table.

The table exists so that adding a mode is one row rather than four edits. These
tests pin the round-trip: every mode must map a stored binding back to itself.
"""

import unittest

from linghub.ui.binding_modes import (
    BY_NAME,
    MODE_BUTTON,
    MODE_CHORD,
    MODE_KEY,
    MODE_KEY_MACRO,
    MODE_NOTHING,
    MODE_SPECIAL,
    MODES,
    is_single_key_macro,
    mode_for,
    single_key_of,
    stored_binding,
)


class ModeTableTests(unittest.TestCase):
    def test_every_mode_has_a_label(self):
        for mode in MODES:
            self.assertTrue(mode.label.strip(), f"{mode.name} has no label")

    def test_mode_names_are_unique(self):
        names = [mode.name for mode in MODES]
        self.assertEqual(len(names), len(set(names)))

    def test_every_mode_is_in_the_lookup(self):
        for mode in MODES:
            self.assertIs(BY_NAME[mode.name], mode)

    def test_every_mode_stores_a_known_kind(self):
        valid = {"key", "macro", "special", "button", "disabled"}
        for mode in MODES:
            self.assertIn(mode.kind, valid, f"{mode.name} stores {mode.kind}")


class ModeForTests(unittest.TestCase):
    def test_a_key_opens_as_a_key(self):
        self.assertEqual(mode_for("key", "KEY_X"), MODE_KEY)

    def test_a_single_key_macro_opens_as_its_own_mode(self):
        """Not as a chord: re-saving would change the mechanism."""
        self.assertEqual(mode_for("macro", "KEY_X"), MODE_KEY_MACRO)

    def test_a_real_chord_opens_as_a_chord(self):
        self.assertEqual(
            mode_for("macro", "+KEY_LEFTCTRL +KEY_C -KEY_C -KEY_LEFTCTRL"),
            MODE_CHORD,
        )

    def test_special_and_button_and_disabled(self):
        self.assertEqual(mode_for("special", "resolution-up"), MODE_SPECIAL)
        self.assertEqual(mode_for("button", "4"), MODE_BUTTON)
        self.assertEqual(mode_for("disabled", None), MODE_NOTHING)

    def test_an_unknown_kind_falls_back_to_key(self):
        self.assertEqual(mode_for("nonsense", "x"), MODE_KEY)


class StoredBindingTests(unittest.TestCase):
    def test_every_mode_round_trips(self):
        cases = [
            (MODE_KEY, "KEY_X", ("key", "KEY_X")),
            (MODE_KEY_MACRO, "KEY_X", ("macro", "KEY_X")),
            (MODE_CHORD, "+KEY_A +KEY_B -KEY_B -KEY_A",
             ("macro", "+KEY_A +KEY_B -KEY_B -KEY_A")),
            (MODE_SPECIAL, "resolution-up", ("special", "resolution-up")),
            (MODE_BUTTON, "4", ("button", 4)),
            (MODE_NOTHING, "", ("disabled", None)),
        ]
        for mode, value, expected in cases:
            with self.subTest(mode=mode):
                self.assertEqual(stored_binding(mode, value), expected)

    def test_a_button_value_becomes_an_int(self):
        self.assertIsInstance(stored_binding(MODE_BUTTON, "7")[1], int)

    def test_a_key_macro_stores_the_macro_kind(self):
        """The whole point: same value, different mechanism."""
        self.assertEqual(stored_binding(MODE_KEY_MACRO, "KEY_X")[0], "macro")
        self.assertEqual(stored_binding(MODE_KEY, "KEY_X")[0], "key")


class SingleKeyMacroTests(unittest.TestCase):
    def test_one_key_is_a_single_key_macro(self):
        self.assertTrue(is_single_key_macro("KEY_X"))

    def test_a_chord_is_not(self):
        self.assertFalse(is_single_key_macro("+KEY_LEFTCTRL +KEY_C -KEY_C -KEY_LEFTCTRL"))

    def test_a_timed_sequence_is_not(self):
        self.assertFalse(is_single_key_macro("KEY_A t100 KEY_B"))

    def test_empty_is_not(self):
        self.assertFalse(is_single_key_macro(""))

    def test_the_key_is_extracted(self):
        self.assertEqual(single_key_of("KEY_X"), "KEY_X")


if __name__ == "__main__":
    unittest.main()
