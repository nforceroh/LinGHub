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


if __name__ == "__main__":
    unittest.main()
