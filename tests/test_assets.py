"""The files the app reads at runtime must ship inside the package.

A packaged install has no clone to find them in, so a path that resolves
outside `linghub/` works in development and breaks once installed. These
tests pin the paths to the package and check the files are there.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from linghub.ui import buttonmap


PACKAGE = Path(buttonmap.__file__).resolve().parent


class PackagedAssetTests(unittest.TestCase):
    def test_the_diagram_is_inside_the_package(self):
        self.assertTrue(buttonmap.DIAGRAM_IMAGE.exists(), buttonmap.DIAGRAM_IMAGE)
        self.assertEqual(buttonmap.DIAGRAM_IMAGE.parent.parent, PACKAGE)

    def test_the_packaged_hotspots_are_inside_the_package(self):
        self.assertTrue(buttonmap.PACKAGED_HOTSPOTS.exists())
        self.assertEqual(buttonmap.PACKAGED_HOTSPOTS.parent, PACKAGE)

    def test_the_window_uses_the_packaged_diagram(self):
        from linghub.ui import window

        self.assertEqual(window.IMAGE, buttonmap.DIAGRAM_IMAGE)


class HotspotsLocationTests(unittest.TestCase):
    """Placed hotspots are user data, not configuration (ADR-0004, ADR-0011)."""

    def test_user_hotspots_live_under_the_xdg_data_directory(self):
        with mock.patch.dict(os.environ, {"XDG_DATA_HOME": "/tmp/xdg-data"}):
            self.assertEqual(
                buttonmap.user_hotspots(),
                Path("/tmp/xdg-data/linghub/hotspots.json"),
            )

    def test_user_hotspots_fall_back_to_local_share(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                buttonmap.user_hotspots(),
                Path.home() / ".local" / "share" / "linghub" / "hotspots.json",
            )

    def test_the_packaged_file_is_used_until_the_user_places_their_own(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"XDG_DATA_HOME": tmp}):
                self.assertEqual(buttonmap.hotspots_file(), buttonmap.PACKAGED_HOTSPOTS)

                user = buttonmap.user_hotspots()
                user.parent.mkdir(parents=True)
                user.write_text('{"hotspots": []}', encoding="utf-8")
                self.assertEqual(buttonmap.hotspots_file(), user)

    def test_a_user_file_replaces_the_packaged_positions(self):
        with tempfile.TemporaryDirectory() as tmp:
            user = Path(tmp) / "linghub" / "hotspots.json"
            user.parent.mkdir(parents=True)
            user.write_text(
                '{"hotspots": [{"index": 0, "x": 0.5, "y": 0.5}]}', encoding="utf-8"
            )
            with mock.patch.dict(os.environ, {"XDG_DATA_HOME": tmp}):
                positions = buttonmap.load_positions()
        self.assertEqual(positions[0], (0.5, 0.5))
        # Buttons the user has not placed keep the packaged positions.
        self.assertEqual(positions[1], buttonmap.FALLBACK_POSITIONS[1])
