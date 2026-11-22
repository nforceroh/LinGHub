"""Tests for the window's display decisions.

These used to be untestable without constructing a GTK widget by hand. They are
pure functions of daemon state and the current selection, so they can be tested
directly.
"""

import unittest

from linghub.daemon_view import ViewState
from linghub.ui.presentation import (
    binding_label,
    editing_profile,
)


def state(active="desktop", profiles=("desktop", "wot"), desktop="desktop"):
    return ViewState(
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


class BindingLabelTests(unittest.TestCase):
    def test_a_known_binding_is_described(self):
        self.assertEqual(binding_label({0: ("key", "KEY_F")}, 0), "F")

    def test_an_unset_button_shows_a_dash(self):
        self.assertEqual(binding_label({}, 3), "—")

    def test_an_empty_kind_shows_a_dash(self):
        self.assertEqual(binding_label({3: ("", None)}, 3), "—")


if __name__ == "__main__":
    unittest.main()
