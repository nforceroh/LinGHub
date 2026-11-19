"""Tests for the main window.

The window builds GTK widgets, so these need a display. They cover the
profile list, the panels' dirty state, the write path's status messages,
profile management, and the separation of selecting from loading.
"""

import unittest

from .support import has_cairo, make_window, view


@unittest.skipUnless(has_cairo(), "needs pycairo and Gtk 4")
class ProfileListTests(unittest.TestCase):
    """The profile list must survive the two-second poll.

    Rebuilding every row from scratch on each poll destroyed the user's
    selection, so clicking a profile appeared to bounce back to whatever was
    listed first.
    """

    def _window(self, active="desktop"):
        return make_window(active=active)

    def test_selecting_a_profile_sticks(self):
        window = self._window()
        window._profile_list.select_row(window._profile_list.get_row_at_index(2))
        selected = window._profile_list.get_selected_row()
        self.assertIsNotNone(selected)
        self.assertEqual(selected.get_title(), "star-citizen")

    def test_a_refresh_does_not_clear_the_selection(self):
        window = self._window()
        window._profile_list.select_row(window._profile_list.get_row_at_index(2))

        # Same state again, as a refresh would deliver.
        window._apply_view(view())

        selected = window._profile_list.get_selected_row()
        self.assertIsNotNone(selected, "the refresh cleared the selection")
        self.assertEqual(selected.get_title(), "star-citizen")

    def test_rows_are_not_recreated_on_every_refresh(self):
        """Recreating rows is what loses focus and selection."""
        window = self._window()
        first = window._profile_list.get_row_at_index(1)

        window._apply_view(view())
        self.assertIs(window._profile_list.get_row_at_index(1), first)

    def test_active_marker_moves_without_rebuilding(self):
        window = self._window(active="desktop")
        self.assertIn(
            "on the mouse",
            window._profile_list.get_row_at_index(0).get_subtitle(),
        )
        window._apply_view(view(active="world-of-tanks"))
        self.assertIn(
            "on the mouse",
            window._profile_list.get_row_at_index(1).get_subtitle(),
        )


@unittest.skipUnless(has_cairo(), "needs pycairo and Gtk 4")
class LedSaveModelTests(unittest.TestCase):
    """Editing must not write, and a poll must not clobber unsaved edits."""

    def _window(self):
        return make_window(profiles=("desktop",), panels=True)

    def test_editing_does_not_call_the_client(self):
        calls = []

        class FakeClient:
            async def set_leds(self, *a):
                calls.append(a)
                return True

        window = self._window()
        window._client = FakeClient()
        panel = window._led_panel
        for value in range(100, 121):
            panel._brightness.set_value(value)
        self.assertEqual(calls, [], "editing wrote to the daemon")

    def test_a_refresh_does_not_discard_unsaved_edits(self):
        window = self._window()
        panel = window._led_panel
        panel.load({0: {"mode": "on", "color": (255, 0, 0),
                        "brightness": 100, "duration": 0}})
        panel._brightness.set_value(222)
        self.assertTrue(panel.dirty)

        # A refresh arrives with the old values from disk.
        leds = {0: {"mode": "on", "color": (255, 0, 0),
                    "brightness": 100, "duration": 0}}
        window._apply_view(view(profiles=("desktop",), leds=leds))

        self.assertEqual(panel.brightness, 222, "the refresh reverted the edit")
        self.assertTrue(panel.dirty)

    def test_a_refresh_reloads_a_clean_panel(self):
        window = self._window()
        panel = window._led_panel
        panel.load({0: {"mode": "on", "color": (255, 0, 0),
                        "brightness": 100, "duration": 0}})
        leds = {0: {"mode": "off", "color": (0, 0, 0),
                    "brightness": 50, "duration": 0}}
        window._apply_view(view(profiles=("desktop",), leds=leds))
        self.assertEqual(panel.mode, "off")


@unittest.skipUnless(has_cairo(), "needs pycairo and Gtk 4")
class WriteStatusTests(unittest.TestCase):
    """A write's message must survive its own refresh.

    Applying a view overwrites the status line, so a write that reports its
    outcome and then refreshes in the background loses the message. The write
    path waits for the refresh before it reports.

    The message is transient: the next poll replaces it with the state line.
    That is deliberate - the status line belongs to the poll, and a write only
    borrows it long enough to say what happened.
    """

    def _window(self):
        return make_window(profiles=("desktop",), editing="desktop")

    def test_a_write_message_is_not_lost_to_its_own_refresh(self):
        import asyncio

        class FakeClient:
            async def load_profile(self, name):
                return True

            async def get_view(self, _profile):
                return view(profiles=("desktop",))

            async def daemon_version(self):
                from linghub import version

                return version.DaemonVersion.known(version.current())

        window = self._window()
        window._client = FakeClient()

        async def run():
            await window._load_profile("desktop")

        asyncio.run(run())
        self.assertIn(
            "Loaded desktop", window._status.get_text(),
            "the refresh overwrote the write's message",
        )


@unittest.skipUnless(has_cairo(), "needs pycairo and Gtk 4")
class ProfileManagementUiTests(unittest.TestCase):
    """The desktop profile must never be deletable, from any entry point."""

    def _window(self):
        return make_window(profiles=("desktop", "wot"))

    def test_selected_profile_is_read_from_the_list(self):
        window = self._window()
        window._profile_list.select_row(window._profile_list.get_row_at_index(1))
        self.assertEqual(window._selected_profile(), "wot")

    def test_no_selection_returns_none(self):
        self.assertIsNone(self._window()._selected_profile())

    def test_deleting_the_desktop_profile_is_refused_before_the_daemon(self):
        calls = []

        class FakeClient:
            async def delete_profile(self, name):
                calls.append(name)
                return True

        window = self._window()
        window._client = FakeClient()
        window._profile_list.select_row(window._profile_list.get_row_at_index(0))
        window._prompt_delete_profile()
        self.assertEqual(calls, [], "the desktop profile was sent to the daemon")
        self.assertIn("cannot be deleted", window._status.get_text().lower())

    def test_delete_without_a_selection_says_so(self):
        window = self._window()
        window._prompt_delete_profile()
        self.assertIn("select a profile", window._status.get_text().lower())


def _in_loop(fn, *args):
    """Run a synchronous call inside a loop, as the GTK loop would.

    `_select_profile` starts a refresh, which schedules a task and so needs a
    running loop. Production always has one; a test has to make one.
    """
    import asyncio

    async def run():
        return fn(*args)

    return asyncio.run(run())


@unittest.skipUnless(has_cairo(), "needs pycairo and Gtk 4")
class SelectionVersusLoadingTests(unittest.TestCase):
    """Selecting a profile edits it; it must not load it onto the mouse.

    These were the same gesture, so editing a gaming profile meant writing it
    to the mouse and making the mouse use it - and with no game running the
    daemon then reverted it two seconds later.
    """

    def _window(self):
        return make_window(profiles=("desktop", "world-of-tanks"))

    def test_selecting_a_profile_does_not_load_it(self):
        calls = []

        class FakeClient:
            async def load_profile(self, name):
                calls.append(name)
                return True

        window = self._window()
        window._client = FakeClient()
        _in_loop(window._select_profile, "world-of-tanks")
        self.assertEqual(calls, [], "selecting a profile loaded it onto the mouse")

    def test_selecting_a_gaming_profile_makes_it_the_edit_target(self):
        window = self._window()
        _in_loop(window._select_profile, "world-of-tanks")
        self.assertEqual(window._editing_profile(), "world-of-tanks")

    def test_a_gaming_profile_is_editable_with_no_game_running(self):
        """The whole point: editing must not require loading."""
        window = self._window()
        _in_loop(window._select_profile, "world-of-tanks")
        self.assertEqual(window._editing_profile(), "world-of-tanks")
        self.assertEqual(window._state.active_profile, "desktop")

    def test_the_edit_target_defaults_to_the_active_profile(self):
        window = self._window()
        self.assertEqual(window._editing_profile(), "desktop")

    def test_loading_is_a_separate_action(self):
        """Loading is its own gesture, driven by the selection."""
        import asyncio

        calls = []

        class FakeClient:
            async def load_profile(self, name):
                calls.append(name)
                return True

            async def get_view(self, _profile):
                return view(profiles=("desktop", "world-of-tanks"))

            async def daemon_version(self):
                from linghub import version

                return version.DaemonVersion.known(version.current())

        window = self._window()
        window._client = FakeClient()
        # _load_selected goes through the GLib bridge, which needs a main loop;
        # drive the coroutine it would run instead. The factory's scheduler
        # puts the refresh on this loop, so the await in _refresh_now works.

        async def run():
            window._select_profile("world-of-tanks")
            await window._load_profile(window._editing_profile())

        asyncio.run(run())
        self.assertEqual(calls, ["world-of-tanks"])



@unittest.skipUnless(has_cairo(), "needs pycairo and Gtk 4")
class VersionTests(unittest.TestCase):
    """The window shows its app version, and flags a daemon on other code."""

    def setUp(self):
        from linghub import version

        self.version = version
        self.window = make_window()

    def test_a_matching_daemon_shows_no_banner(self):
        self.window._apply_daemon_version(self.version.DaemonVersion.known(self.version.current()))
        self.assertFalse(self.window._banner.get_revealed())

    def test_a_different_daemon_says_to_restart_it(self):
        self.window._apply_daemon_version(self.version.DaemonVersion.known("9.9.9"))
        self.assertTrue(self.window._banner.get_revealed())
        self.assertEqual(self.window._banner.get_title(), "Daemon is running 9.9.9; restart it")

    def test_an_old_daemon_predates_version_reporting(self):
        self.window._apply_daemon_version(self.version.DaemonVersion.predates_reporting())
        self.assertTrue(self.window._banner.get_revealed())
        self.assertEqual(
            self.window._banner.get_title(), "Daemon predates version reporting; restart it"
        )

    def test_no_daemon_is_not_a_mismatch(self):
        self.window._apply_daemon_version(self.version.DaemonVersion.known("9.9.9"))
        self.window._apply_daemon_version(self.version.DaemonVersion.not_running())
        self.assertFalse(self.window._banner.get_revealed())

    def test_the_about_dialog_shows_both_versions(self):
        self.window._apply_daemon_version(self.version.DaemonVersion.known("9.9.9"))
        dialog = self.window._about_dialog()
        self.assertEqual(dialog.get_version(), self.version.current())
        self.assertIn("Daemon  9.9.9", dialog.get_comments())

    def test_the_about_dialog_says_when_the_daemon_is_not_running(self):
        self.window._apply_daemon_version(self.version.DaemonVersion.not_running())
        self.assertIn("Daemon  not running", self.window._about_dialog().get_comments())

    def test_a_refresh_reads_the_daemon_version(self):
        import asyncio

        class FakeClient:
            async def get_view(self, _profile):
                return view()

            async def daemon_version(self):
                from linghub import version

                return version.DaemonVersion.known("9.9.9")

        self.window._client = FakeClient()
        asyncio.run(self.window._read_and_apply())
        self.assertTrue(self.window._banner.get_revealed())

    def test_a_failed_version_read_does_not_break_the_refresh(self):
        import asyncio

        class FakeClient:
            async def get_view(self, _profile):
                return view(active="world-of-tanks")

            async def daemon_version(self):
                raise RuntimeError("Get failed")

        self.window._client = FakeClient()
        asyncio.run(self.window._read_and_apply())
        self.assertIn("world-of-tanks", self.window._status.get_text())
        self.assertFalse(self.window._banner.get_revealed())

    def test_a_failed_version_read_does_not_say_the_daemon_is_not_running(self):
        """The bug: About said "Daemon not running" while the daemon ran."""
        import asyncio

        class FakeClient:
            async def get_view(self, _profile):
                return view(active="world-of-tanks")

            async def daemon_version(self):
                raise RuntimeError("Get failed")

        self.window._client = FakeClient()
        asyncio.run(self.window._read_and_apply())
        comments = self.window._about_dialog().get_comments()
        self.assertNotIn("not running", comments)
        self.assertIn("Daemon  unreadable", comments)


if __name__ == "__main__":
    unittest.main()
