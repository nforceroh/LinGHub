"""Tests for the manage-profiles canvas.

The canvas is a view in the main window, so most of these drive the window
directly: opening it, its actions, and what a refused write leaves behind.
The pure bits — the summary line and the tile text — get their own class,
since they are the part a user reads.
"""

import unittest

from .support import has_cairo, make_window, view


def summary_line(name="wot", dpi=800, rate=1000, games=()):
    from linghub.daemon_view import ProfileSummary

    return ProfileSummary(name=name, dpi=dpi, report_rate=rate, games=games)


class SummaryLineTests(unittest.TestCase):
    """The tile's one line, which is what a user compares across profiles."""

    def test_both_facts(self):
        from linghub.ui.manage_tile import profile_summary_line

        self.assertEqual(
            profile_summary_line(summary_line()), "800 DPI · 1000 Hz"
        )

    def test_no_default_preset(self):
        """A hand-edited config can lack a default; that is not "0 DPI"."""
        from linghub.ui.manage_tile import profile_summary_line

        self.assertEqual(profile_summary_line(summary_line(dpi=0)), "1000 Hz")

    def test_no_report_rate(self):
        from linghub.ui.manage_tile import profile_summary_line

        self.assertEqual(profile_summary_line(summary_line(rate=0)), "800 DPI")

    def test_neither(self):
        from linghub.ui.manage_tile import profile_summary_line

        self.assertEqual(profile_summary_line(summary_line(dpi=0, rate=0)), "")


@unittest.skipUnless(has_cairo(), "needs pycairo and Gtk 4")
class CanvasFillTests(unittest.TestCase):
    """What the canvas shows after a read."""

    def _window(self):
        return make_window(profiles=("desktop", "wot"))

    def test_every_profile_has_a_tile(self):
        window = self._window()
        window._fill_canvas(view())
        self.assertEqual(
            list(window._manage._profile_tiles),
            ["desktop", "world-of-tanks", "star-citizen"],
        )

    def test_a_stale_tile_goes_away_after_a_delete(self):
        """The canvas reads the same view the panels do, so a delete clears."""
        window = self._window()
        window._fill_canvas(view(profiles=("desktop", "world-of-tanks", "star-citizen")))
        window._fill_canvas(view(profiles=("desktop", "wot")))
        self.assertEqual(list(window._manage._profile_tiles), ["desktop", "wot"])

    def test_the_desktop_profile_has_no_delete(self):
        window = self._window()
        window._fill_canvas(view(profiles=("desktop",)))
        tile = window._manage._profile_tiles["desktop"]
        self.assertEqual(
            [child for child in tile if isinstance(child, type(tile))], []
        )

    def test_the_desktop_profile_has_no_delete(self):
        window = self._window()
        window._fill_canvas(view(profiles=("desktop",)))
        tile = window._manage._profile_tiles["desktop"]
        self.assertEqual(
            [child for child in tile if isinstance(child, type(tile))], []
        )

    def test_a_profile_shows_the_game_it_is_tied_to(self):
        window = self._window()
        window._fill_canvas(view(summaries=(
            summary_line(name="wot", games=(("WorldOfTanks.exe", "World of Tanks"),)),
        )))
        tile = window._manage._profile_tiles["wot"]
        self.assertEqual(tile.game_name, "World of Tanks")

    def test_a_gameless_profile_shows_no_game(self):
        window = self._window()
        window._fill_canvas(view(summaries=(summary_line(name="desktop"),)))
        tile = window._manage._profile_tiles["desktop"]
        self.assertIsNone(tile.game_name)

    def test_there_is_no_separate_games_row(self):
        window = self._window()
        window._fill_canvas(view())
        self.assertFalse(hasattr(window._manage, "_games_row"))

    def test_the_add_tile_starts_the_add_game_flow(self):
        """Profiles are created through a game, so ADD PROFILE is gone."""
        window = self._window()
        window._fill_canvas(view())
        self.assertEqual(window._manage._add_game_tile.get_label(), "+ ADD GAME")

    def test_the_canvas_is_hidden_until_opened(self):
        window = self._window()
        self.assertEqual(window._stack.get_visible_child_name(), "home")


@unittest.skipUnless(has_cairo(), "needs pycairo and Gtk 4")
class CanvasNavigationTests(unittest.TestCase):
    """Opening and leaving the canvas, and the pending-edits prompt."""

    def _window(self):
        return make_window(profiles=("desktop", "wot"), editing="desktop")

    def test_opening_shows_the_canvas(self):
        window = self._window()
        window._open_manage_profiles()
        self.assertEqual(window._stack.get_visible_child_name(), "manage")
        self.assertTrue(window._back_button.get_visible())

    def test_back_returns_to_the_editor_without_changing_the_editing_profile(self):
        """The canvas is a place you navigate to; its way back is not "pick something"."""
        window = self._window()
        window._show_view("editor")
        window._open_manage_profiles()
        window._back_clicked()
        self.assertEqual(window._stack.get_visible_child_name(), "editor")
        self.assertEqual(window._editing_profile(), "desktop")
        self.assertTrue(window._back_button.get_visible())

    def test_back_from_the_editor_goes_home(self):
        window = self._window()
        window._show_view("editor")
        window._back_clicked()
        self.assertEqual(window._stack.get_visible_child_name(), "home")
        self.assertFalse(window._back_button.get_visible())

    def test_opening_with_pending_edits_prompts_first(self):
        """The prompt holds the canvas shut until the user answers it."""
        window = self._window()
        window._start_binding_write("desktop", 2, "key", "KEY_X")
        window._open_manage_profiles()
        self.assertNotEqual(window._stack.get_visible_child_name(), "manage")


@unittest.skipUnless(has_cairo(), "needs pycairo and Gtk 4")
class CanvasDetailsTests(unittest.TestCase):
    """DETAILS closes the canvas and edits the profile, without loading it."""

    def _window(self):
        return make_window(profiles=("desktop", "wot"), editing="desktop")

    def test_details_edits_without_loading(self):
        import asyncio

        loads = []

        class FakeClient:
            async def load_profile(self, name):
                loads.append(name)
                return True

            async def get_view(self, _profile):
                return view(profiles=("desktop", "wot"))

            async def daemon_version(self):
                from linghub import version

                return version.DaemonVersion.not_running()

        window = self._window()
        window._client = FakeClient()

        async def run():
            window._open_manage_profiles()
            window._canvas_details("wot")
            for _ in range(5):
                await asyncio.sleep(0)

        asyncio.run(run())
        self.assertEqual(loads, [], "DETAILS loaded the profile")
        self.assertEqual(window._editing_profile(), "wot")
        self.assertEqual(window._stack.get_visible_child_name(), "editor")
        self.assertTrue(window._back_button.get_visible())

    def test_details_with_pending_edits_prompts(self):
        """The prompt holds the switch until the user answers it."""
        window = self._window()
        window._open_manage_profiles()
        self.assertEqual(window._stack.get_visible_child_name(), "manage")
        window._start_binding_write("desktop", 2, "key", "KEY_X")
        window._canvas_details("wot")
        # No answer to the prompt yet: nothing has changed.
        self.assertEqual(window._editing_profile(), "desktop")


@unittest.skipUnless(has_cairo(), "needs pycairo and Gtk 4")
class CanvasWriteTests(unittest.TestCase):
    """The canvas's writes: add game, duplicate, delete."""

    def _window(self):
        return make_window(profiles=("desktop", "wot"))

    def test_adding_a_game_creates_a_profile_carrying_it(self):
        import asyncio

        calls = []

        class FakeClient:
            async def create_profile(self, name, executable):
                calls.append(("create", name, executable))
                return True

            async def rename_game(self, profile, executable, name):
                calls.append(("rename_game", profile, executable, name))
                return True

            async def get_view(self, _profile):
                return view(profiles=("desktop", "wot"))

            async def daemon_version(self):
                from linghub import version

                return version.DaemonVersion.not_running()

        window = self._window()
        window._client = FakeClient()

        asyncio.run(window._actions._create_game_profile(
            "WorldOfTanks.exe", "World of Tanks", "wot-new"
        ))
        self.assertEqual(
            calls,
            [
                ("create", "wot-new", "WorldOfTanks.exe"),
                ("rename_game", "wot-new", "WorldOfTanks.exe", "World of Tanks"),
            ],
        )

    def test_adding_a_game_to_an_existing_profile_is_refused(self):
        calls = []

        class FakeClient:
            async def create_profile(self, *a):
                calls.append(a)
                return True

        window = self._window()
        window._client = FakeClient()
        window._actions.create_game_profile("WoT.exe", "", "wot")
        self.assertEqual(calls, [])
        self.assertIn("already exists", window._status.get_text())

    def test_a_nameless_game_skips_the_rename(self):
        import asyncio

        calls = []

        class FakeClient:
            async def create_profile(self, name, executable):
                calls.append(("create",))
                return True

            async def rename_game(self, *a):
                calls.append(("rename_game",))
                return True

            async def get_view(self, _profile):
                return view(profiles=("desktop",))

            async def daemon_version(self):
                from linghub import version

                return version.DaemonVersion.not_running()

        window = self._window()
        window._client = FakeClient()

        asyncio.run(window._actions._create_game_profile("WoT.exe", "", "new"))
        self.assertEqual(calls, [("create",)])

    def test_a_refused_create_says_so(self):
        import asyncio

        class RefusingClient:
            async def create_profile(self, *a):
                return False

            async def get_view(self, _profile):
                return view(profiles=("desktop",))

            async def daemon_version(self):
                from linghub import version

                return version.DaemonVersion.not_running()

        window = self._window()
        window._client = RefusingClient()

        asyncio.run(window._actions._create_game_profile("WoT.exe", "WoT", "desktop"))
        self.assertIn("cannot add", window._status.get_text().lower())

    def test_duplicating_calls_the_daemon(self):
        import asyncio

        calls = []

        class FakeClient:
            async def duplicate_profile(self, name, new):
                calls.append((name, new))
                return True

            async def get_view(self, _profile):
                return view(profiles=("desktop",))

            async def daemon_version(self):
                from linghub import version

                return version.DaemonVersion.not_running()

        window = self._window()
        window._client = FakeClient()

        asyncio.run(
            window._actions._duplicate_profile("wot", "wot copy", _FakeDialog())
        )
        self.assertEqual(calls, [("wot", "wot copy")])

    def test_deleting_the_desktop_from_the_canvas_is_refused(self):
        calls = []

        class FakeClient:
            async def delete_profile(self, name):
                calls.append(name)
                return True

        window = self._window()
        window._client = FakeClient()
        window._actions.prompt_delete_from_canvas("desktop")
        self.assertEqual(calls, [])
        self.assertIn("cannot be deleted", window._status.get_text().lower())


class _FakeDialog:
    """Whatever a write path may ask of a prompt, recorded instead of shown."""

    def __init__(self):
        self.errors = []
        self.closed = False

    def show_error(self, message):
        self.errors.append(message)

    def close(self):
        self.closed = True


if __name__ == "__main__":
    unittest.main()
