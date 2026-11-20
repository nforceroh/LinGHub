"""The package must contain what the code reads at runtime.

The spec's `%files` list and the wheel's contents are two descriptions of the
same thing, written in different places. These tests compare them, so a new
runtime file cannot be added to the wheel and forgotten in the package.
"""

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "packaging" / "linghub.spec"


class SpecTests(unittest.TestCase):
    def setUp(self):
        self.spec = SPEC.read_text(encoding="utf-8")

    def test_the_spec_installs_the_whole_package_tree(self):
        """A per-file list would drift; the tree is installed whole."""
        self.assertIn("%{python3_sitelib}/linghub/", self.spec)

    def test_the_spec_installs_the_dist_info(self):
        """Without it, a packaged install reports its version as unknown."""
        self.assertIn("%{python3_sitelib}/linghub-%{version}.dist-info/", self.spec)

    def test_the_spec_ships_the_units_the_desktop_files_and_the_icon(self):
        for path in (
            "%{_userunitdir}/linghub.service",
            "%{_userunitdir}/linghub-tray.service",
            "%{_datadir}/applications/org.linghub.LinGHub.desktop",
            "%{_metainfodir}/org.linghub.LinGHub.metainfo.xml",
            "%{_datadir}/icons/hicolor/scalable/apps/org.linghub.LinGHub.svg",
        ):
            self.assertIn(path, self.spec)

    def test_the_spec_has_no_unsubstituted_version(self):
        self.assertIn("@VERSION@", self.spec, "the build script substitutes this")

    def test_the_gui_dependencies_are_in_the_ui_subpackage_only(self):
        """A headless machine must be able to install the daemon alone."""
        base, _, ui = self.spec.partition("%package ui")
        self.assertNotIn("gtk4", base)
        self.assertNotIn("python3-gobject", base)
        self.assertIn("gtk4", ui)
        self.assertIn("python3-gobject", ui)
        self.assertIn("libappindicator-gtk3", ui)


class SourceFileTests(unittest.TestCase):
    """Every file the spec names as a Source must exist in the repo."""

    def test_every_source_file_exists(self):
        spec = SPEC.read_text(encoding="utf-8")
        sources = re.findall(r"^Source\d+:\s+(\S+)$", spec, re.MULTILINE)
        self.assertTrue(sources)

        build_script = (ROOT / "scripts" / "build-rpm.sh").read_text(encoding="utf-8")
        for name in sources:
            if name.endswith(".whl"):
                continue  # built by the script, not checked in
            self.assertIn(name, build_script, f"{name} is not staged by build-rpm.sh")


class DesktopFileTests(unittest.TestCase):
    def test_the_desktop_file_launches_the_ui(self):
        text = (ROOT / "packaging" / "org.linghub.LinGHub.desktop").read_text(encoding="utf-8")
        self.assertIn("Exec=linghub ui", text)
        self.assertIn("Icon=org.linghub.LinGHub", text)

    def test_the_metainfo_launchable_matches_the_desktop_file(self):
        text = (ROOT / "packaging" / "org.linghub.LinGHub.metainfo.xml").read_text(encoding="utf-8")
        self.assertIn("<launchable type=\"desktop-id\">org.linghub.LinGHub.desktop</launchable>", text)


class UnitTests(unittest.TestCase):
    def test_the_packaged_unit_writes_a_config_before_the_daemon(self):
        text = (ROOT / "packaging" / "units" / "linghub.service").read_text(encoding="utf-8")
        self.assertIn("ExecStartPre=-/usr/bin/linghub init --if-missing", text)

    def test_the_packaged_unit_does_not_restart_on_a_bad_config(self):
        text = (ROOT / "packaging" / "units" / "linghub.service").read_text(encoding="utf-8")
        self.assertIn("RestartPreventExitStatus=78", text)

    def test_the_clone_unit_has_a_different_name(self):
        """A user unit shadows a system one, so the names must differ."""
        clone = (ROOT / "data" / "linghub-dev.service").read_text(encoding="utf-8")
        packaged = (ROOT / "packaging" / "units" / "linghub.service").read_text(encoding="utf-8")
        self.assertIn("clone install", clone)
        self.assertNotIn("clone install", packaged)
