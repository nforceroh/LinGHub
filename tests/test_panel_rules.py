"""Tests for the rules the panels used to hold inside GTK callbacks.

Each of these was previously only reachable by constructing a widget, so none
of them had a test of its own: the speed inversion was covered indirectly
through `LedPanel`, and the "only one default" rule not at all.
"""

import unittest

from linghub.ui.device import rules as panel_rules
from linghub.ui.device.rules import (
    MODES,
    SPEED_MAX,
    SPEED_MIN,
    controls_for,
    default_mask,
    duration_to_speed,
    speed_to_duration,
)


class SpeedConversionTests(unittest.TestCase):
    """The slider is a speed: higher means faster, so lower duration."""

    def test_higher_speed_means_shorter_duration(self):
        self.assertLess(speed_to_duration(18), speed_to_duration(2))

    def test_a_duration_round_trips_within_the_slider_step(self):
        for duration in (1000, 3000, 8000, 20000):
            with self.subTest(duration=duration):
                speed = duration_to_speed(duration)
                self.assertAlmostEqual(speed_to_duration(speed), duration, delta=1200)

    def test_speed_is_clamped_to_the_slider_range(self):
        self.assertEqual(duration_to_speed(1), SPEED_MAX)
        self.assertEqual(duration_to_speed(10_000_000), SPEED_MIN)

    def test_zero_duration_does_not_divide_by_zero(self):
        self.assertEqual(duration_to_speed(0), panel_rules.FALLBACK_SPEED)

    def test_a_zero_speed_does_not_divide_by_zero(self):
        """A slider at 0 would otherwise raise rather than produce a duration."""
        self.assertEqual(speed_to_duration(0), 20_000)


class EffectControlTests(unittest.TestCase):
    def test_a_looping_effect_has_a_speed(self):
        self.assertTrue(controls_for("cycle").speed)
        self.assertTrue(controls_for("breathing").speed)

    def test_a_fixed_colour_has_no_speed(self):
        self.assertFalse(controls_for("on").speed)

    def test_off_has_no_speed_and_no_colour(self):
        controls = controls_for("off")
        self.assertFalse(controls.speed)
        self.assertFalse(controls.color)
        self.assertFalse(controls.brightness)

    def test_a_lit_effect_enables_colour_and_brightness(self):
        for mode in ("on", "cycle", "breathing"):
            with self.subTest(mode=mode):
                self.assertTrue(controls_for(mode).color)
                self.assertTrue(controls_for(mode).brightness)


class DefaultExclusivityTests(unittest.TestCase):
    """The hardware honours exactly one default slot."""

    def test_turning_one_on_clears_the_others(self):
        mask = default_mask([False, True, False], 0, on=True)
        self.assertEqual(mask, (True, False, False))

    def test_turning_one_on_when_none_were_set(self):
        mask = default_mask([False, False, False], 2, on=True)
        self.assertEqual(mask, (False, False, True))

    def test_turning_one_off_leaves_the_others_alone(self):
        """It must not promote a neighbour the user did not ask for."""
        mask = default_mask([True, False, False], 0, on=False)
        self.assertEqual(mask, (False, False, False))

    def test_a_hand_edited_double_default_is_not_duplicated(self):
        mask = default_mask([True, True, False], 2, on=True)
        self.assertEqual(mask, (False, False, True))

    def test_an_out_of_range_index_changes_nothing(self):
        before = [True, False]
        self.assertEqual(default_mask(before, 5, on=True), (True, False))
        self.assertEqual(default_mask(before, 5, on=False), (True, False))


class ModeVocabularyTests(unittest.TestCase):
    """The order is hardware fact: libratbag's enum, not presentation."""

    def test_modes_match_the_hardware_enum(self):
        self.assertEqual(
            [name for name, _label in MODES],
            ["off", "on", "cycle", "breathing"],
        )

    def test_every_mode_has_a_label(self):
        for name, label in MODES:
            self.assertTrue(label.strip(), f"{name} has no label")

    def test_animated_modes_are_a_subset_of_modes(self):
        names = {name for name, _label in MODES}
        self.assertTrue(set(panel_rules.ANIMATED_MODES) <= names)


if __name__ == "__main__":
    unittest.main()