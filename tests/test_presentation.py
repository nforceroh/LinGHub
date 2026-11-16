"""Tests for the window's display decisions.

These used to be untestable without constructing a GTK widget by hand. They are
pure functions of daemon state and the current selection, so they can be tested
directly.
"""

import unittest

from linghub.ui.client import DaemonState
from linghub.ui.presentation import (
    binding_label,
    binding_labels,
    editing_profile,
    profile_rows,
)


def state(active="desktop", profiles=("desktop", "wot"), desktop="desktop"):
    return DaemonState(
        active_profile=active, profiles=profiles, desktop_profile=desktop
    )


class EditingProfileTests(unittest.TestCase):
    def test_the_selection_wins(self):
        """A gaming profile can be edited without being loaded."""
        self.assertEqual(editing_profile(state(), "wot"), "wot")

    def test_falls_back_to_what_is_loaded(self):
        self.assertEqual(editing_profile(state(active="wot"), None), "wot")

    def test_falls_back_to_the_desktop_profile(self):
        self.assertEqual(editing_profile(state(active=""), None), "desktop")

    def test_falls_back_to_the_first_profile(self):
        self.assertEqual(
            editing_profile(state(active="", desktop="gone"), None), "desktop"
        )

    def test_a_stale_selection_is_ignored(self):
        """A deleted profile must not stay the edit target."""
        self.assertEqual(editing_profile(state(active="wot"), "deleted"), "wot")

    def test_no_profiles_means_no_target(self):
        self.assertIsNone(editing_profile(state(active="", profiles=()), None))


class ProfileRowTests(unittest.TestCase):
    def test_one_row_per_profile_in_order(self):
        rows = profile_rows(state(), None)
        self.assertEqual([r.name for r in rows], ["desktop", "wot"])

    def test_the_loaded_profile_is_marked(self):
        rows = profile_rows(state(active="wot"), None)
        self.assertTrue(rows[1].on_the_mouse)
        self.assertFalse(rows[0].on_the_mouse)

    def test_the_edited_profile_is_marked(self):
        rows = profile_rows(state(), "wot")
        self.assertTrue(rows[1].editing)
        self.assertFalse(rows[0].editing)

    def test_loaded_and_edited_can_differ(self):
        """The whole point of separating them."""
        rows = profile_rows(state(active="desktop"), "wot")
        self.assertTrue(rows[0].on_the_mouse)
        self.assertFalse(rows[0].editing)
        self.assertFalse(rows[1].on_the_mouse)
        self.assertTrue(rows[1].editing)

    def test_the_desktop_profile_is_marked(self):
        rows = profile_rows(state(), None)
        self.assertTrue(rows[0].is_desktop)
        self.assertFalse(rows[1].is_desktop)

    def test_subtitle_names_both_facts(self):
        rows = profile_rows(state(active="wot"), "wot")
        self.assertEqual(rows[1].subtitle, "on the mouse · editing")

    def test_subtitle_is_empty_when_neither_applies(self):
        rows = profile_rows(state(active="desktop"), "wot")
        self.assertEqual(rows[0].subtitle, "on the mouse")
        self.assertEqual(rows[1].subtitle, "editing")


class BindingLabelTests(unittest.TestCase):
    def test_a_known_binding_is_described(self):
        self.assertEqual(binding_label({0: ("key", "KEY_F")}, 0), "F")

    def test_an_unset_button_shows_a_dash(self):
        self.assertEqual(binding_label({}, 3), "—")

    def test_an_empty_kind_shows_a_dash(self):
        self.assertEqual(binding_label({3: ("", None)}, 3), "—")

    def test_every_index_gets_a_label(self):
        labels = binding_labels({0: ("key", "KEY_F")}, [0, 1, 2])
        self.assertEqual(sorted(labels), [0, 1, 2])
        self.assertEqual(labels[1], "—")


if __name__ == "__main__":
    unittest.main()
