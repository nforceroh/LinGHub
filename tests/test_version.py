"""Tests for the app version: how git's answer becomes the string we show.

The git calls are injected, so these run without a clone and pin the exact
strings the tray, window and CLI compare. See ADR-0009.
"""

import subprocess
import unittest
from pathlib import Path

from linghub import version


def runner(answers: dict[tuple[str, ...], str | None]):
    """A fake `git` that answers known commands and fails the rest."""

    def run(args: list[str]) -> str:
        answer = answers.get(tuple(args))
        if answer is None:
            raise subprocess.CalledProcessError(128, ["git", *args])
        return answer

    return run


DESCRIBE = ("describe", "--tags", "--long", "--dirty", "--match", "v[0-9]*")
COUNT = ("rev-list", "--count", "HEAD")
HASH = ("describe", "--always", "--dirty", "--abbrev=7")


class FromGitTests(unittest.TestCase):
    def test_a_tagged_commit_is_the_bare_release(self):
        run = runner({DESCRIBE: "v0.1.0-0-g5c27eef"})
        self.assertEqual(version.from_git(run), "0.1.0")

    def test_commits_past_a_tag_carry_the_count_and_hash(self):
        run = runner({DESCRIBE: "v0.1.0-3-g5c27eef"})
        self.assertEqual(version.from_git(run), "0.1.0+3.g5c27eef")

    def test_uncommitted_changes_are_marked(self):
        run = runner({DESCRIBE: "v0.1.0-3-g5c27eef-dirty"})
        self.assertEqual(version.from_git(run), "0.1.0+3.g5c27eef.dirty")

    def test_a_dirty_tagged_commit_is_not_the_bare_release(self):
        """Edits on top of a release are not that release."""
        run = runner({DESCRIBE: "v0.1.0-0-g5c27eef-dirty"})
        self.assertEqual(version.from_git(run), "0.1.0+0.g5c27eef.dirty")

    def test_no_tag_yet_counts_from_zero(self):
        run = runner({COUNT: "65", HASH: "5c27eef"})
        self.assertEqual(version.from_git(run), "0.0.0+65.g5c27eef")

    def test_no_tag_yet_still_marks_uncommitted_changes(self):
        run = runner({COUNT: "65", HASH: "5c27eef-dirty"})
        self.assertEqual(version.from_git(run), "0.0.0+65.g5c27eef.dirty")

    def test_no_usable_git_gives_none(self):
        self.assertIsNone(version.from_git(runner({})))

    def test_a_missing_git_binary_gives_none(self):
        def run(_args):
            raise FileNotFoundError("git")

        self.assertIsNone(version.from_git(run))

    def test_an_unrecognised_describe_gives_none(self):
        run = runner({DESCRIBE: "something-else"})
        self.assertIsNone(version.from_git(run))


class ResolveTests(unittest.TestCase):
    def test_a_clone_is_read_from_git(self):
        found = version.resolve(
            clone=Path("/repo"), git=lambda _clone: "0.1.0+1.gabc1234",
            installed=lambda: "0.1.0",
        )
        self.assertEqual(found, "0.1.0+1.gabc1234")

    def test_without_a_clone_the_installed_version_is_used(self):
        found = version.resolve(
            clone=None, git=lambda _clone: self.fail("git read without a clone"),
            installed=lambda: "0.2.0",
        )
        self.assertEqual(found, "0.2.0")

    def test_an_unreadable_clone_falls_back_to_the_installed_version(self):
        found = version.resolve(
            clone=Path("/repo"), git=lambda _clone: None, installed=lambda: "0.2.0",
        )
        self.assertEqual(found, "0.2.0")

    def test_nothing_known_is_unknown(self):
        found = version.resolve(clone=None, git=lambda _c: None, installed=lambda: None)
        self.assertEqual(found, "unknown")


class DaemonNoteTests(unittest.TestCase):
    """What a client says about the daemon's version next to its own."""

    def test_the_same_version_needs_no_note(self):
        self.assertIsNone(version.daemon_note("0.1.0+3.g5c27eef", "0.1.0+3.g5c27eef"))

    def test_a_different_version_says_to_restart(self):
        self.assertEqual(
            version.daemon_note("0.1.0+4.gabc1234", "0.1.0+3.g5c27eef"),
            "Daemon is running 0.1.0+3.g5c27eef; restart it",
        )

    def test_a_daemon_without_a_version_predates_reporting(self):
        self.assertEqual(
            version.daemon_note("0.1.0", version.PREDATES_REPORTING),
            "Daemon predates version reporting; restart it",
        )


class NoDaemonTests(unittest.TestCase):
    def test_no_daemon_is_not_a_mismatch(self):
        self.assertIsNone(version.daemon_note("0.1.0", version.DAEMON_NOT_RUNNING))


class CurrentTests(unittest.TestCase):
    def test_the_version_is_fixed_at_first_read(self):
        """A process reports what it loaded at startup, not today's checkout."""
        self.assertIs(version.current(), version.current())

    def test_this_checkout_reports_a_real_version(self):
        self.assertNotEqual(version.current(), "unknown")


if __name__ == "__main__":
    unittest.main()
