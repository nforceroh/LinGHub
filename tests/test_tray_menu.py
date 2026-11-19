"""Tests for the tray menu's structure.

These need GTK3, which cannot share a process with GTK4, so they run in a
subprocess. That keeps the main suite free to import the GTK4 UI.
"""

import subprocess
import sys
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent

SCRIPT = r"""
import sys
sys.path.insert(0, {src!r})
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("AppIndicator3", "0.1")
from linghub.tray import Tray
from linghub.ui.client import DaemonState

tray = Tray()
tray._apply(DaemonState(
    active_profile="desktop",
    profiles=("desktop", "world-of-tanks", "star-citizen"),
    desktop_profile="desktop",
))
print("SUBMENU_VISIBLE", tray._profiles_menu.get_visible())
print("PARENT_VISIBLE", tray._profiles_box.get_visible())
print("ITEMS", ",".join(i.get_label() for i in tray._profile_items))
print("ITEM_VISIBLE", ",".join(str(i.get_visible()) for i in tray._profile_items))
print("SENSITIVE", ",".join(str(i.get_sensitive()) for i in tray._profile_items))
print("STATUS", tray._status_item.get_label())
from linghub import version
print("VERSION_LABEL", tray._version_item.get_label())
print("VERSION_SENSITIVE", tray._version_item.get_sensitive())
print("VERSION_IS_LAST", tray._menu.get_children()[-1] is tray._daemon_note_item
      and tray._menu.get_children()[-2] is tray._version_item)
tray._apply_version(version.current())
print("NOTE_WHEN_SAME", tray._daemon_note_item.get_visible())
tray._apply_version("9.9.9")
print("NOTE_WHEN_DIFFERENT", tray._daemon_note_item.get_visible())
print("NOTE_TEXT", tray._daemon_note_item.get_label())
tray._apply_version(version.PREDATES_REPORTING)
print("NOTE_WHEN_OLD", tray._daemon_note_item.get_label())
tray._apply_version(version.DAEMON_NOT_RUNNING)
print("NOTE_WHEN_ABSENT", tray._daemon_note_item.get_visible())
print("FALLBACK_REPEATS", tray._refresh())
print("ONCE_REMOVES", tray._refresh_once())
"""


def run_menu():
    result = subprocess.run(
        [sys.executable, "-c", SCRIPT.format(src=str(REPO / "src"))],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise AssertionError(f"tray menu script failed:\n{result.stderr}")
    values = {}
    for line in result.stdout.splitlines():
        key, _, value = line.partition(" ")
        values[key] = value
    return values


class TrayMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.menu = run_menu()

    def test_the_submenu_is_visible(self):
        """A hidden submenu renders as an empty arrow, which looks broken."""
        self.assertEqual(self.menu["SUBMENU_VISIBLE"], "True")

    def test_the_parent_item_is_visible(self):
        self.assertEqual(self.menu["PARENT_VISIBLE"], "True")

    def test_every_profile_has_an_entry(self):
        self.assertEqual(
            self.menu["ITEMS"], "desktop,world-of-tanks,star-citizen"
        )

    def test_every_entry_is_visible(self):
        self.assertEqual(self.menu["ITEM_VISIBLE"], "True,True,True")

    def test_the_active_profile_is_not_selectable(self):
        """Loading the profile already loaded would be a no-op."""
        self.assertEqual(self.menu["SENSITIVE"], "False,True,True")

    def test_the_status_line_names_the_active_profile(self):
        self.assertIn("desktop", self.menu["STATUS"])

    def test_the_fallback_timer_stays_armed(self):
        """Returning SOURCE_REMOVE would kill the poll after its first fire."""
        self.assertEqual(self.menu["FALLBACK_REPEATS"], "True")

    def test_a_signal_refresh_does_not_rearm(self):
        """idle_add removes the source; a truthy return would repeat forever."""
        self.assertEqual(self.menu["ONCE_REMOVES"], "False")


class TrayVersionTests(unittest.TestCase):
    """The tray shows its app version, and the daemon's when it differs."""

    @classmethod
    def setUpClass(cls):
        from linghub import version

        cls.menu = run_menu()
        cls.own = version.current()

    def test_the_tray_shows_its_own_version(self):
        self.assertEqual(self.menu["VERSION_LABEL"], f"LinGHub {self.own}")

    def test_the_version_line_is_not_clickable(self):
        self.assertEqual(self.menu["VERSION_SENSITIVE"], "False")

    def test_the_version_lines_close_the_menu(self):
        self.assertEqual(self.menu["VERSION_IS_LAST"], "True")

    def test_a_matching_daemon_shows_no_note(self):
        self.assertEqual(self.menu["NOTE_WHEN_SAME"], "False")

    def test_a_different_daemon_says_to_restart_it(self):
        self.assertEqual(self.menu["NOTE_WHEN_DIFFERENT"], "True")
        self.assertEqual(self.menu["NOTE_TEXT"], "Daemon is running 9.9.9; restart it")

    def test_an_old_daemon_predates_version_reporting(self):
        self.assertEqual(
            self.menu["NOTE_WHEN_OLD"], "Daemon predates version reporting; restart it"
        )

    def test_no_daemon_is_not_a_mismatch(self):
        self.assertEqual(self.menu["NOTE_WHEN_ABSENT"], "False")


if __name__ == "__main__":
    unittest.main()
