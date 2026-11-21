"""Tests for the main window.

The window builds GTK widgets, so these need a display. They cover the
profile list, the panels' dirty state, the write path's status messages,
profile management, and the separation of selecting from loading.
"""

import unittest

from .support import has_cairo, make_window, view


@unittest.skipUnless(has_cairo(), "needs pycairo and Gtk 4")
class ProfileSelectorTests(unittest.TestCase):
    """The selector must survive a refresh without losing the user's place.

    Rebuilding every row from scratch on each refresh destroyed the selection,
    so choosing a profile appeared to bounce back to whatever was listed first.
    """

    def _window(self, active="desktop"):
        return make_window(active=active)

    def test_every_profile_has_a_row(self):
        window = self._window()
        self.assertEqual(
            list(window._selector._rows), ["desktop", "world-of-tanks", "star-citizen"]
        )

    def test_the_label_shows_the_profile_being_edited(self):
        window = self._window()
        self.assertEqual(window._selector._label.get_text(), "desktop")

    def test_a_refresh_does_not_recreate_the_rows(self):
        """Recreating rows is what loses focus and selection."""
        window = self._window()
        first = window._selector._rows["world-of-tanks"]

        window._apply_view(view())
        self.assertIs(window._selector._rows["world-of-tanks"], first)

    def test_the_active_marker_moves_without_rebuilding(self):
        window = self._window(active="desktop")
        self.assertTrue(window._selector._rows["desktop"]._check.get_visible())
        self.assertFalse(window._selector._rows["world-of-tanks"]._check.get_visible())

        window._apply_view(view(active="world-of-tanks"))
        self.assertFalse(window._selector._rows["desktop"]._check.get_visible())
        self.assertTrue(window._selector._rows["world-of-tanks"]._check.get_visible())

    def test_a_profile_that_goes_away_loses_its_row(self):
        window = self._window()
        window._apply_view(view(profiles=("desktop",)))
        self.assertEqual(list(window._selector._rows), ["desktop"])

    def test_the_search_field_is_hidden_for_a_short_list(self):
        window = self._window()
        self.assertFalse(window._selector._search.get_visible())

    def test_the_search_field_appears_for_a_long_list(self):
        from linghub.ui.profile_selector import SEARCH_THRESHOLD

        names = tuple(f"p{n}" for n in range(SEARCH_THRESHOLD))
        window = self._window()
        window._apply_view(view(profiles=names))
        self.assertTrue(window._selector._search.get_visible())

    def test_searching_hides_the_rows_that_do_not_match(self):
        window = self._window()
        window._selector._search.set_text("star")
        self.assertTrue(window._selector._rows["star-citizen"].get_visible())
        self.assertFalse(window._selector._rows["desktop"].get_visible())

    def test_searching_ignores_case(self):
        window = self._window()
        window._selector._search.set_text("STAR")
        self.assertTrue(window._selector._rows["star-citizen"].get_visible())


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

    def test_the_profile_being_edited_is_the_one_acted_on(self):
        """There is no list to select from; the selector's choice is the target."""
        window = self._window()
        window._editing = "wot"
        self.assertEqual(window._editing_profile(), "wot")

    def test_deleting_the_desktop_profile_is_refused_before_the_daemon(self):
        calls = []

        class FakeClient:
            async def delete_profile(self, name):
                calls.append(name)
                return True

        window = self._window()
        window._client = FakeClient()
        window._editing = "desktop"
        window._prompt_delete_profile()
        self.assertEqual(calls, [], "the desktop profile was sent to the daemon")
        self.assertIn("cannot be deleted", window._status.get_text().lower())

    def test_delete_with_no_profile_says_so(self):
        from linghub.daemon_view import ViewState

        window = self._window()
        window._state = ViewState()
        window._editing = None
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
class ChoosingLoadsTests(unittest.TestCase):
    """Choosing a profile from the selector loads it onto the mouse.

    This reverses what the window used to do. Selecting a profile used to only
    choose what to edit, and a separate `Load` button put it on the mouse. Two
    actions on one list is the thing users are least likely to expect, so the
    selector does both.
    """

    def _window(self):
        return make_window(profiles=("desktop", "world-of-tanks"))

    def test_choosing_a_profile_loads_it(self):
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

        async def run():
            window._choose_profile("world-of-tanks")
            # The load is scheduled on the loop; let it finish.
            for _ in range(5):
                await asyncio.sleep(0)

        asyncio.run(run())
        self.assertEqual(calls, ["world-of-tanks"])

    def test_choosing_makes_it_the_edit_target(self):
        window = self._window()
        _in_loop(window._choose_profile, "world-of-tanks")
        self.assertEqual(window._editing_profile(), "world-of-tanks")

    def test_choosing_the_profile_already_being_edited_does_nothing(self):
        """Re-choosing the current profile must not reload it."""
        window = self._window()
        window._editing = "desktop"
        _in_loop(window._choose_profile, "desktop")
        self.assertEqual(window._editing, "desktop")

    def test_the_edit_target_defaults_to_the_active_profile(self):
        window = self._window()
        self.assertEqual(window._editing_profile(), "desktop")

    def test_a_refused_load_still_shows_the_chosen_profile(self):
        """The panels follow the choice, not the load's outcome.

        Editing a profile that is not on the mouse is a legitimate state, so a
        refused load must not leave the panels showing the previous profile's
        bindings under the new one's name.
        """
        import asyncio

        window = self._window()

        class RefusingClient:
            async def load_profile(self, name):
                return False

            async def get_view(self, _profile):
                return view(profiles=("desktop", "world-of-tanks"))

            async def daemon_version(self):
                from linghub import version

                return version.DaemonVersion.not_running()

        window._client = RefusingClient()

        async def run():
            window._choose_profile("world-of-tanks")
            for _ in range(6):
                await asyncio.sleep(0)

        asyncio.run(run())
        self.assertEqual(window._editing_profile(), "world-of-tanks")
        self.assertEqual(
            window._selector._label.get_text(), "world-of-tanks",
            "the selector still showed the previous profile",
        )

    def test_a_refused_load_says_so(self):
        """A refusal must not be silent: the user clicked and nothing happened."""
        import asyncio

        window = self._window()

        class RefusingClient:
            async def load_profile(self, name):
                return False

            async def get_view(self, _profile):
                return view(profiles=("desktop", "world-of-tanks"))

            async def daemon_version(self):
                from linghub import version

                return version.DaemonVersion.not_running()

        window._client = RefusingClient()

        async def run():
            window._choose_profile("world-of-tanks")
            for _ in range(6):
                await asyncio.sleep(0)

        asyncio.run(run())
        self.assertIn("refused", window._status.get_text().lower())


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


@unittest.skipUnless(has_cairo(), "needs pycairo and Gtk 4")
class FirstReadTests(unittest.TestCase):
    """The first read cannot name a profile, so it must be followed by another.

    With no state yet the window asks the daemon for "", which answers with the
    profile list but no profile's sections. The panels then sat empty until
    something unrelated triggered a read, which is how the DPI slots went
    missing on a freshly opened window.
    """

    def test_an_unnamed_first_read_asks_again_once_the_state_is_known(self):
        import asyncio

        window = make_window(profiles=("desktop", "world-of-tanks"))
        # A freshly opened window: no state yet, so no profile to name.
        from linghub.daemon_view import ViewState

        window._state = ViewState()
        window._editing = None
        asked = []

        class FakeClient:
            async def get_view(self, profile):
                asked.append(profile)
                return view(profiles=("desktop", "world-of-tanks"))

            async def daemon_version(self):
                from linghub import version

                return version.DaemonVersion.not_running()

        window._client = FakeClient()

        async def run():
            await window._read_and_apply()

        asyncio.run(run())
        self.assertEqual(asked, [""])
        self.assertTrue(
            window._refresh_pending,
            "the window must ask again now that it knows which profile to edit",
        )

    def test_a_named_read_does_not_ask_again(self):
        import asyncio

        window = make_window(profiles=("desktop",), editing="desktop")
        asked = []

        class FakeClient:
            async def get_view(self, profile):
                asked.append(profile)
                return view(profiles=("desktop",))

            async def daemon_version(self):
                from linghub import version

                return version.DaemonVersion.not_running()

        window._client = FakeClient()

        async def run():
            await window._read_and_apply()

        asyncio.run(run())
        self.assertEqual(asked, ["desktop"])
        self.assertFalse(window._refresh_pending)


class SaveAndDiscardTests(unittest.TestCase):
    """One Save and one Discard for every section, in the header.

    Bindings used to be written the moment the editor's Apply was pressed, so
    "discard my changes" could not be offered honestly. Now every edit is held
    until Save.
    """

    def _window(self):
        return make_window(profiles=("desktop", "world-of-tanks"), editing="desktop")

    def test_the_buttons_start_disabled(self):
        window = self._window()
        self.assertFalse(window._save_button.get_sensitive())
        self.assertFalse(window._discard_button.get_sensitive())

    def test_a_pending_binding_enables_both(self):
        window = self._window()
        window._start_binding_write("desktop", 2, "key", "KEY_X")
        self.assertTrue(window._save_button.get_sensitive())
        self.assertTrue(window._discard_button.get_sensitive())

    def test_a_pending_binding_is_not_written_immediately(self):
        """The whole point: nothing reaches the daemon until Save."""
        window = self._window()
        calls = []

        class FakeClient:
            async def set_binding(self, *args):
                calls.append(args)
                return True

        window._client = FakeClient()
        window._start_binding_write("desktop", 2, "key", "KEY_X")
        self.assertEqual(calls, [])

    def test_discard_forgets_the_pending_edits(self):
        import asyncio

        window = self._window()
        window._start_binding_write("desktop", 2, "key", "KEY_X")

        async def run():
            window._discard_changes()
            # The refresh it kicks off needs a loop to run on.
            await asyncio.sleep(0)

        asyncio.run(run())
        self.assertFalse(window._pending.dirty)
        self.assertFalse(window._save_button.get_sensitive())

    def test_discard_does_not_write_anything(self):
        import asyncio

        window = self._window()
        calls = []

        class FakeClient:
            async def set_binding(self, *args):
                calls.append(args)
                return True

            async def get_view(self, _profile):
                return view(profiles=("desktop", "world-of-tanks"))

            async def daemon_version(self):
                from linghub import version

                return version.DaemonVersion.known(version.current())

        window._client = FakeClient()
        window._start_binding_write("desktop", 2, "key", "KEY_X")

        async def run():
            window._discard_changes()
            await asyncio.sleep(0)

        asyncio.run(run())
        self.assertEqual(calls, [])

    def test_save_writes_every_pending_section(self):
        import asyncio

        window = self._window()
        calls = []

        class FakeClient:
            async def set_binding(self, profile, index, kind, value):
                calls.append(("binding", index, kind, value))
                return True

            async def set_resolution(self, profile, index, dpi, **kw):
                calls.append(("resolution", index, dpi))
                return True

            async def set_report_rate(self, profile, rate):
                calls.append(("rate", rate))
                return True

            async def set_leds(self, profile, mode, brightness, duration, color):
                calls.append(("leds", mode))
                return True

            async def get_view(self, _profile):
                return view(profiles=("desktop", "world-of-tanks"))

            async def daemon_version(self):
                from linghub import version

                return version.DaemonVersion.known(version.current())

        window._client = FakeClient()
        window._start_binding_write("desktop", 2, "key", "KEY_X")
        window._pending.for_profile("desktop").set_resolutions([(800, True, False)], 1000)
        window._pending.for_profile("desktop").set_leds("breathing", 255, 8000, (1, 2, 3))

        asyncio.run(window._do_save("desktop"))

        kinds = [call[0] for call in calls]
        self.assertIn("binding", kinds)
        self.assertIn("resolution", kinds)
        self.assertIn("rate", kinds)
        self.assertIn("leds", kinds)

    def test_a_successful_save_clears_the_pending_edits(self):
        import asyncio

        window = self._window()

        class FakeClient:
            async def set_binding(self, *args):
                return True

            async def get_view(self, _profile):
                return view(profiles=("desktop", "world-of-tanks"))

            async def daemon_version(self):
                from linghub import version

                return version.DaemonVersion.known(version.current())

        window._client = FakeClient()
        window._start_binding_write("desktop", 2, "key", "KEY_X")
        asyncio.run(window._do_save("desktop"))
        self.assertFalse(window._pending.dirty)

    def test_a_refused_save_keeps_the_pending_edits(self):
        """So the user can fix the problem and press Save again."""
        import asyncio

        window = self._window()

        class FakeClient:
            async def set_binding(self, *args):
                return False

            async def get_view(self, _profile):
                return view(profiles=("desktop", "world-of-tanks"))

            async def daemon_version(self):
                from linghub import version

                return version.DaemonVersion.known(version.current())

        window._client = FakeClient()
        window._start_binding_write("desktop", 2, "key", "KEY_X")
        asyncio.run(window._do_save("desktop"))
        self.assertTrue(window._pending.dirty, "a refused save discarded the edits")

    def test_switching_profiles_with_pending_edits_asks_first(self):
        window = self._window()
        window._start_binding_write("desktop", 2, "key", "KEY_X")
        window._choose_profile("world-of-tanks")
        self.assertEqual(
            window._editing, "desktop",
            "the switch happened without asking",
        )

    def test_switching_with_nothing_pending_just_switches(self):
        import asyncio

        window = self._window()

        async def run():
            window._choose_profile("world-of-tanks")
            await asyncio.sleep(0)

        asyncio.run(run())
        self.assertEqual(window._editing, "world-of-tanks")


@unittest.skipUnless(has_cairo(), "needs pycairo and Gtk 4")
class HomeScreenTests(unittest.TestCase):
    """The window opens on the device card, and the mouse opens the editor."""

    def _window(self):
        return make_window(profiles=("desktop",))

    def test_the_window_opens_on_the_home_screen(self):
        window = self._window()
        self.assertEqual(window._stack.get_visible_child_name(), "home")

    def test_the_back_button_is_hidden_at_home(self):
        window = self._window()
        self.assertFalse(window._back_button.get_visible())

    def test_clicking_the_mouse_opens_the_editor(self):
        window = self._window()
        window._show_view("editor")
        self.assertEqual(window._stack.get_visible_child_name(), "editor")
        self.assertTrue(window._back_button.get_visible())

    def test_the_back_button_returns_home(self):
        window = self._window()
        window._show_view("editor")
        window._show_view("home")
        self.assertEqual(window._stack.get_visible_child_name(), "home")
        self.assertFalse(window._back_button.get_visible())

    def test_the_card_names_the_mouse(self):
        window = self._window()
        window._card.show_device("G502 LIGHTSPEED", None)
        self.assertEqual(window._card._name.get_text(), "G502 LIGHTSPEED")

    def test_a_wired_mouse_shows_no_battery_line(self):
        window = self._window()
        window._card.show_device("G502", None)
        self.assertFalse(window._card._battery.get_visible())

    def test_a_wireless_mouse_shows_its_charge(self):
        from linghub.hardware.battery import Battery

        window = self._window()
        window._card.show_device("G502", Battery(capacity=85, charging=False))
        self.assertTrue(window._card._battery.get_visible())
        self.assertEqual(window._card._battery.get_text(), "85%")

    def test_a_charging_mouse_says_so(self):
        from linghub.hardware.battery import Battery

        window = self._window()
        window._card.show_device("G502", Battery(capacity=40, charging=True))
        self.assertEqual(window._card._battery.get_text(), "40% · charging")
