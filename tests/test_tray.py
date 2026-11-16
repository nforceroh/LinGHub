"""Tests for the tray process.

The tray is GTK3 in a separate process, so these cover the parts that do not
need a display: the command it launches and the fact that importing it does not
drag in GTK4.
"""

import unittest


class IsolationTests(unittest.TestCase):
    def test_tray_does_not_import_gtk4(self):
        """GTK3 and GTK4 cannot be loaded together, so the tray must stay GTK3.

        This reads the module source rather than importing it, because importing
        would load GTK3 into this test process and break any later GTK4 import.
        """
        from pathlib import Path

        source = (
            Path(__file__).resolve().parent.parent / "src" / "linghub" / "tray.py"
        ).read_text()
        self.assertIn('gi.require_version("Gtk", "3.0")', source)
        self.assertNotIn('gi.require_version("Gtk", "4.0")', source)
        self.assertNotIn("from .window", source)
        self.assertNotIn("from .dpi_panel", source)

    def test_tray_does_not_touch_hardware(self):
        """The tray asks the daemon; it must not talk to ratbagd itself."""
        import ast
        from pathlib import Path

        tree = ast.parse(
            (Path(__file__).resolve().parent.parent / "src" / "linghub" / "tray.py")
            .read_text()
        )
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)

        offenders = sorted(
            name for name in imported
            if "hardware" in name or "ratbag" in name
        )
        self.assertEqual(offenders, [], f"the tray imports {offenders}")

    def test_the_ui_is_launched_as_a_subprocess(self):
        """It cannot be imported: the UI is GTK4 and the tray is GTK3."""
        from pathlib import Path

        source = (
            Path(__file__).resolve().parent.parent / "src" / "linghub" / "tray.py"
        ).read_text()
        self.assertIn("subprocess.Popen", source)
        self.assertIn("linghub ui", source)


if __name__ == "__main__":
    unittest.main()
