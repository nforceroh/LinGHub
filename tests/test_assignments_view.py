"""The Assignments view: selection, staging and refresh through its interface.

These tests construct the view normally — GTK and cairo are importable here —
so the interface is the test surface: refresh, set_selected, selected, and
the stage callback. Nothing pokes _table_rows or _diagram; those are
implementation and may change freely.
"""

import unittest

from .support import has_cairo
from linghub.ui.assignments.view import AssignmentsView


def make_view(**kwargs):
    """A real view with recording callbacks."""
    staged: list[tuple[int, str, object]] = []
    statuses: list[str] = []
    view = AssignmentsView(
        on_stage=lambda index, kind, value: staged.append((index, kind, value)),
        on_status=statuses.append,
        **kwargs,
    )
    return view, staged, statuses


@unittest.skipUnless(has_cairo(), "needs pycairo and Gtk 4")
class SelectionTests(unittest.TestCase):
    def test_a_selection_is_answered(self):
        view, _staged, _statuses = make_view()
        view.set_selected(7)
        self.assertEqual(view.selected(), 7)

    def test_selection_survives_a_refresh(self):
        view, _staged, _statuses = make_view()
        view.set_selected(7)
        view.refresh({}, {})
        self.assertEqual(view.selected(), 7)


@unittest.skipUnless(has_cairo(), "needs pycairo and Gtk 4")
class EditorOpeningTests(unittest.TestCase):
    """A table-row click opens the editor: the click-to-edit affordance
    (spec §2.9, Q51). This was dropped once in an extraction and is pinned
    here so it stays."""

    def test_a_row_click_selects_then_opens(self):
        opened: list[tuple[int, str, object]] = []
        view, _staged, _statuses = make_view(
            on_open_editor=lambda index, kind, value: opened.append(
                (index, kind, value)
            ),
        )
        view.refresh({7: ("key", "KEY_7")}, {})
        view._on_row_clicked(7)
        self.assertEqual(view.selected(), 7)
        self.assertEqual(opened, [(7, "key", "KEY_7")])

    def test_an_unbound_row_opens_as_nothing(self):
        opened: list[tuple[int, str, object]] = []
        view, _staged, _statuses = make_view(
            on_open_editor=lambda index, kind, value: opened.append(
                (index, kind, value)
            ),
        )
        view._on_row_clicked(7)
        self.assertEqual(opened, [(7, "disabled", None)])

    def test_no_callback_opens_nothing(self):
        view, _staged, _statuses = make_view()
        view.refresh({7: ("key", "KEY_7")}, {})
        view._on_row_clicked(7)  # must not raise


@unittest.skipUnless(has_cairo(), "needs pycairo and Gtk 4")
class StagingTests(unittest.TestCase):
    def test_a_chosen_assignment_is_staged_for_the_selected_button(self):
        view, staged, _statuses = make_view()
        view.set_selected(7)
        view._on_chosen("key", "KEY_7")
        self.assertEqual(staged, [(7, "key", "KEY_7")])

    def test_a_drop_selects_then_stages(self):
        view, staged, _statuses = make_view()

        class Choice:
            kind = "key"
            value = "KEY_9"

        view._on_dropped(None, 8, Choice())
        self.assertEqual(view.selected(), 8)
        self.assertEqual(staged, [(8, "key", "KEY_9")])

    def test_no_selection_means_nothing_is_staged(self):
        view, staged, statuses = make_view()
        view._on_chosen("key", "KEY_7")
        self.assertEqual(staged, [])
        self.assertTrue(statuses)


if __name__ == "__main__":
    unittest.main()
