"""Tests for the Assignments sidebar choices."""

import unittest

from linghub.ui.assignment_sidebar import (
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
