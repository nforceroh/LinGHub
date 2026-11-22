"""The Assignments view: selection, staging and refresh through its interface.

These tests used to need the whole window: the view's state lived on the
window as private fields, so a drop or a selection could only be exercised by
building a half-constructed MainWindow. The view now owns that state, so the
tests cross its interface — refresh, set_selected, and the stage callback.
"""

import unittest

from gi.repository import Gtk

from linghub.ui.assignments_view import AssignmentsView


def make_view():
    """A view without the diagram: the tests here do not draw."""
    staged: list[tuple[int, str, object]] = []
    statuses: list[str] = []
    view = AssignmentsView.__new__(AssignmentsView)
    Gtk.Paned.__init__(view)
    view._on_stage = lambda index, kind, value: staged.append((index, kind, value))
    view._on_status = statuses.append
    view._selected = None
    view._bindings = {}
    view._pending_bindings = {}
    view._diagram = None
    view._table_rows = {}
    view._binding_rows = {}
    return view, staged, statuses


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
