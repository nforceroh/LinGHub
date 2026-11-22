"""Tests for the Assignments sidebar choices."""

import unittest

from linghub.ui.assignments.catalogue import (
    assignment_choices,
    filter_assignment_choices,
)


class AssignmentChoiceTests(unittest.TestCase):
    def test_every_choice_has_a_kind_and_label(self):
        for choice in assignment_choices():
            self.assertTrue(choice.kind)
            self.assertTrue(choice.label)
            self.assertTrue(choice.group)

    def test_search_matches_labels(self):
        choices = assignment_choices()
        found = filter_assignment_choices(choices, "dpi")
        self.assertTrue(found)
        self.assertTrue(all(
            "dpi" in choice.label.casefold() or "dpi" in choice.group.casefold()
            for choice in found
        ))

    def test_search_is_case_insensitive(self):
        choices = assignment_choices()
        self.assertEqual(
            filter_assignment_choices(choices, "nothing"),
            filter_assignment_choices(choices, "NOTHING"),
        )

    def test_nothing_is_offered(self):
        choices = assignment_choices()
        self.assertIn("Nothing", [choice.label for choice in choices])


class CatalogueConsistencyTests(unittest.TestCase):
    """The sidebar and the editor read one vocabulary, so they cannot drift."""

    def test_the_editor_offers_every_key_the_sidebar_offers(self):
        """A binding staged from the sidebar must be visible in the dialog.

        The editor's key dropdown used to offer only the common keys, so a
        binding staged from the sidebar's full keyboard opened the dialog
        showing whichever key happened to be listed first.
        """
        from linghub.ui.assignments.catalogue import BY_NAME, MODE_KEY

        sidebar_keys = {
            choice.value for choice in assignment_choices()
            if choice.kind == "key"
        }
        editor_keys = {value for value, _label in BY_NAME[MODE_KEY].dropdown_choices()}
        self.assertEqual(sidebar_keys, editor_keys)

    def test_the_macro_mode_offers_the_same_keys(self):
        from linghub.ui.assignments.catalogue import BY_NAME, MODE_KEY, MODE_KEY_MACRO

        key_choices = BY_NAME[MODE_KEY].dropdown_choices()
        macro_choices = BY_NAME[MODE_KEY_MACRO].dropdown_choices()
        self.assertEqual(key_choices, macro_choices)
