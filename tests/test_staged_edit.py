"""The staged-edit rule both panels share.

The panels keep their widgets and their own restore bodies; this module owns
the baseline, the dirty decision, the save guard, and the guard that stops a
programmatic restore from looking like a user edit. These tests pin that rule
without a widget, which is the point of extracting it.
"""

import unittest

from linghub.ui.staged_edit import StagedEdit


class Panel:
    """A stand-in panel: one value, and a record of what it was told."""

    def __init__(self, value=1):
        self.value = value
        self.saved: list[int] = []
        self.restored: list[int] = []
        self.changed: list[bool] = []
        self.staged = StagedEdit(
            lambda: self.value,
            on_save=self.saved.append,
            on_restore=self._restore,
            on_changed=self.changed.append,
        )

    def _restore(self, value):
        self.restored.append(value)
        self.value = value


class DirtyTests(unittest.TestCase):
    def test_a_fresh_panel_is_not_dirty(self):
        panel = Panel()
        panel.staged.mark_saved()
        self.assertFalse(panel.staged.dirty)

    def test_a_changed_value_is_dirty(self):
        panel = Panel()
        panel.staged.mark_saved()
        panel.value = 2
        self.assertTrue(panel.staged.dirty)

    def test_a_panel_with_no_baseline_is_not_dirty(self):
        """Nothing has been loaded, so there is nothing to differ from."""
        self.assertFalse(Panel().staged.dirty)

    def test_returning_to_the_baseline_clears_dirty(self):
        panel = Panel()
        panel.staged.mark_saved()
        panel.value = 2
        panel.value = 1
        self.assertFalse(panel.staged.dirty)


class SaveTests(unittest.TestCase):
    def test_save_publishes_the_values(self):
        panel = Panel()
        panel.staged.mark_saved()
        panel.value = 2
        panel.staged.save()
        self.assertEqual(panel.saved, [2])

    def test_save_does_nothing_when_clean(self):
        panel = Panel()
        panel.staged.mark_saved()
        panel.staged.save()
        self.assertEqual(panel.saved, [])

    def test_mark_saved_accepts_the_current_values(self):
        panel = Panel()
        panel.staged.mark_saved()
        panel.value = 2
        panel.staged.save()
        panel.staged.mark_saved()
        self.assertFalse(panel.staged.dirty)


class RevertTests(unittest.TestCase):
    def test_revert_restores_the_baseline(self):
        panel = Panel()
        panel.staged.mark_saved()
        panel.value = 2
        panel.staged.revert()
        self.assertEqual(panel.restored, [1])
        self.assertEqual(panel.value, 1)

    def test_revert_clears_dirty(self):
        panel = Panel()
        panel.staged.mark_saved()
        panel.value = 2
        panel.staged.revert()
        self.assertFalse(panel.staged.dirty)

    def test_revert_without_a_baseline_does_nothing(self):
        panel = Panel()
        panel.staged.revert()
        self.assertEqual(panel.restored, [])


class RestoringTests(unittest.TestCase):
    """A restore fires the same widget signals a user edit does."""

    def test_edited_is_ignored_while_restoring(self):
        panel = Panel()
        panel.staged.mark_saved()
        panel.changed.clear()
        with panel.staged.restoring():
            panel.staged.edited()
        self.assertEqual(panel.changed, [])

    def test_edited_is_honoured_after_restoring(self):
        panel = Panel()
        panel.staged.mark_saved()
        panel.changed.clear()
        with panel.staged.restoring():
            pass
        panel.value = 2
        panel.staged.edited()
        self.assertEqual(panel.changed, [True])

    def test_the_guard_is_cleared_even_if_the_body_raises(self):
        """A missed finally would leave the panel unable to notice edits."""
        panel = Panel()
        with self.assertRaises(ValueError):
            with panel.staged.restoring():
                raise ValueError("boom")
        self.assertFalse(panel.staged.restoring_now)

    def test_restoring_now_reports_the_guard(self):
        panel = Panel()
        self.assertFalse(panel.staged.restoring_now)
        with panel.staged.restoring():
            self.assertTrue(panel.staged.restoring_now)
        self.assertFalse(panel.staged.restoring_now)

    def test_revert_restores_inside_the_guard(self):
        """The panel's restore body must not be able to mark it dirty."""
        seen = []

        class Watcher(Panel):
            def _restore(self, value):
                seen.append(self.staged.restoring_now)
                super()._restore(value)

        panel = Watcher()
        panel.staged.mark_saved()
        panel.value = 2
        panel.staged.revert()
        self.assertEqual(seen, [True])


class ChangedCallbackTests(unittest.TestCase):
    def test_edited_reports_whether_the_panel_is_dirty(self):
        panel = Panel()
        panel.staged.mark_saved()
        panel.changed.clear()
        panel.value = 2
        panel.staged.edited()
        self.assertEqual(panel.changed, [True])

    def test_mark_saved_reports_clean(self):
        panel = Panel()
        panel.value = 2
        panel.staged.mark_saved()
        self.assertEqual(panel.changed, [False])

    def test_revert_reports_clean(self):
        panel = Panel()
        panel.staged.mark_saved()
        panel.value = 2
        panel.changed.clear()
        panel.staged.revert()
        self.assertEqual(panel.changed, [False])


if __name__ == "__main__":
    unittest.main()
