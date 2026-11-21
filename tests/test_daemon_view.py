"""The daemon/client seam's vocabulary must not drag in a toolkit.

The tray is GTK3 and the window is GTK4. PyGObject loads a GObject namespace
once per process at a fixed version, so a process that has loaded Gtk 3.0
cannot then load Gtk 4.0 — the second `require_version` raises ValueError.
The tray therefore must never import anything that reaches GTK4.

`daemon_access` is imported by the tray, the CLI and the window. It used to
import the view types from `ui.client`, which was safe only because that
module happened to import no GTK. These tests make the guarantee structural:
the types live in a leaf module, and importing `daemon_access` in a GTK3
process is checked rather than assumed.
"""

import subprocess
import sys
import unittest
from pathlib import Path

from linghub import daemon_view


REPO = Path(__file__).resolve().parent.parent


def _gtk3_available() -> bool:
    """True when Gtk 3.0 can be loaded, so the subprocess tests can run.

    Probed in a subprocess on purpose: loading Gtk 3.0 in this process would
    make every later GTK4 import in the suite fail, because PyGObject fixes a
    namespace's version for the life of the process.
    """
    result = subprocess.run(
        [sys.executable, "-c",
         "import gi; gi.require_version('Gtk', '3.0'); "
         "from gi.repository import Gtk"],
        capture_output=True, text=True, timeout=60, cwd=REPO,
    )
    return result.returncode == 0


class LeafTests(unittest.TestCase):
    """`daemon_view` is a leaf: dataclasses and one exception, nothing else."""

    def test_it_imports_no_gtk(self):
        source = Path(daemon_view.__file__).read_text()
        self.assertNotIn("import gi", source)
        self.assertNotIn("gi.repository", source)

    def test_it_imports_nothing_from_the_package(self):
        """A leaf that imported a sibling could inherit that sibling's GTK."""
        source = Path(daemon_view.__file__).read_text()
        self.assertNotIn("from .", source)
        self.assertNotIn("from ..", source)

    def test_the_view_types_are_here(self):
        for name in ("ViewState", "ProfileView", "DaemonView", "DaemonUnavailable"):
            with self.subTest(name=name):
                self.assertTrue(hasattr(daemon_view, name))


@unittest.skipUnless(_gtk3_available(), "needs Gtk 3.0")
class Gtk3ProcessTests(unittest.TestCase):
    """The real failure: a GTK3 process importing the tray's dependencies."""

    def _run(self, code: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=60, cwd=REPO,
        )

    def test_daemon_access_imports_in_a_gtk3_process(self):
        """This is what the tray does at startup. It used to be a landmine:
        one `import gi` added to `ui/client.py` would break it with a
        ValueError at import time."""
        result = self._run(
            "import gi; gi.require_version('Gtk', '3.0'); "
            "import linghub.daemon_access; "
            "print('ok')"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok", result.stdout)

    def test_the_view_types_import_in_a_gtk3_process(self):
        result = self._run(
            "import gi; gi.require_version('Gtk', '3.0'); "
            "from linghub.daemon_view import ViewState, DaemonView; "
            "print(ViewState().desktop_profile)"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("desktop", result.stdout)

    def test_importing_the_window_in_a_gtk3_process_still_fails(self):
        """The constraint is real, not hypothetical: this is why the tray and
        the window are separate processes. If this ever passes, the split can
        be reconsidered."""
        result = self._run(
            "import gi; gi.require_version('Gtk', '3.0'); "
            "import linghub.ui.window"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already requires version", result.stderr)


if __name__ == "__main__":
    unittest.main()
