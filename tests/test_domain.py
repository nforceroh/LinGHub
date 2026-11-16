"""Tests for the domain model itself.

`Profile` and `Binding` are pure, so these need no mocks.
"""

import unittest

from linghub.domain.profile import Binding, Game, Profile


class BindingValueTests(unittest.TestCase):
    """A button binding's value is a button number, however it arrived.

    D-Bus carries every binding value as a string, so a write made from the UI
    delivered `"9"` and that reached the config file. A hand-written file has
    `9`. Both encode to the same action, so nothing ever failed — the two
    files just disagreed.
    """

    def test_a_button_binding_keeps_an_integer(self):
        self.assertEqual(Binding("button", 9).value, 9)

    def test_a_button_binding_from_dbus_text_becomes_an_integer(self):
        binding = Binding("button", "9")
        self.assertIsInstance(binding.value, int)
        self.assertEqual(binding.value, 9)

    def test_a_non_numeric_button_value_is_refused(self):
        with self.assertRaisesRegex(ValueError, "must be a number"):
            Binding("button", "left")

    def test_a_button_value_of_none_is_refused(self):
        """A button binding without a number is not a button binding."""
        with self.assertRaisesRegex(ValueError, "must be a number"):
            Binding("button", None)

    def test_a_boolean_is_not_a_button_number(self):
        """`True` is an int in Python; accepting it would encode as button 1."""
        with self.assertRaisesRegex(ValueError, "must be a number"):
            Binding("button", True)

    def test_other_binding_types_keep_their_value(self):
        self.assertEqual(Binding("key", "KEY_A").value, "KEY_A")
        self.assertEqual(Binding("macro", "KEY_A").value, "KEY_A")
        self.assertEqual(Binding("special", "resolution-up").value, "resolution-up")
        self.assertIsNone(Binding("disabled").value)


class BindingTypeTests(unittest.TestCase):
    def test_an_unknown_type_is_refused(self):
        with self.assertRaisesRegex(ValueError, "unknown binding type"):
            Binding("nonsense")

    def test_every_valid_type_is_accepted(self):
        values = {
            "button": 1, "key": "KEY_A", "macro": "KEY_A",
            "special": "resolution-up", "disabled": None,
        }
        for kind in Binding.VALID_TYPES:
            with self.subTest(type=kind):
                self.assertEqual(Binding(kind, values[kind]).type, kind)


class GameTests(unittest.TestCase):
    def test_an_empty_executable_is_refused(self):
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            Game("  ")

    def test_the_key_is_case_folded(self):
        self.assertEqual(Game("WorldOfTanks.exe").key, "worldoftanks.exe")


class ProfileTests(unittest.TestCase):
    def test_an_empty_name_is_refused(self):
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            Profile(" ")

    def test_a_profile_with_no_games_is_a_desktop_profile(self):
        self.assertTrue(Profile("desktop").is_desktop)

    def test_a_profile_bound_to_a_game_is_a_gaming_profile(self):
        self.assertFalse(Profile("wot", games=(Game("x.exe"),)).is_desktop)


class WithLedsTests(unittest.TestCase):
    """Every LED zone takes the same settings, and nothing else changes."""

    def _profile(self, leds=({"index": 0, "mode": "on"},)):
        return Profile("desktop", leds=tuple(leds))

    def test_every_zone_takes_the_settings(self):
        updated = self._profile().with_leds({"mode": "breathing", "brightness": 100})
        self.assertEqual(
            updated.leds,
            ({"index": 0, "mode": "breathing", "brightness": 100},),
        )

    def test_zone_specific_facts_are_kept(self):
        profile = Profile("desktop", leds=(
            {"index": 0, "mode": "on"},
            {"index": 1, "mode": "on"},
        ))
        updated = profile.with_leds({"mode": "off"})
        self.assertEqual(
            [entry["index"] for entry in updated.leds], [0, 1],
            "the zone indices were lost",
        )

    def test_a_profile_with_no_zones_is_unchanged(self):
        profile = Profile("desktop")
        self.assertEqual(profile.with_leds({"mode": "on"}).leds, ())

    def test_the_original_profile_is_untouched(self):
        profile = self._profile()
        profile.with_leds({"mode": "off"})
        self.assertEqual(profile.leds, ({"index": 0, "mode": "on"},))


if __name__ == "__main__":
    unittest.main()