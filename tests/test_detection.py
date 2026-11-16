"""Tests for process discovery and game detection."""

import os
import unittest
from pathlib import Path

from linghub.discovery.detector import detect
from linghub.discovery.processes import (
    ProcessInfo,
    deduplicate,
    discover_processes,
    read_process,
    should_ignore,
)
from linghub.domain.profile import Game, Profile


def make_process(pid: int, argv0: str, name: str = "proc") -> ProcessInfo:
    return ProcessInfo(
        pid=pid,
        name=name,
        executable_path=argv0,
        real_executable_path="/usr/bin/" + name,
        command=argv0,
    )


class ExecutableNameTests(unittest.TestCase):
    def test_linux_path(self):
        process = make_process(1, "/usr/bin/firefox")
        self.assertEqual(process.executable_name, "firefox")

    def test_wine_path_with_backslashes(self):
        process = make_process(1, r"C:\Games\World_of_Tanks_NA\win64\WorldOfTanks.exe")
        self.assertEqual(process.executable_name, "WorldOfTanks.exe")

    def test_wine_path_with_spaces(self):
        process = make_process(1, r"C:\Program Files\Game\game.exe")
        self.assertEqual(process.executable_name, "game.exe")

    def test_proc_self_exe_falls_back_to_real_path(self):
        process = ProcessInfo(
            pid=1,
            name="game",
            executable_path="/proc/self/exe",
            real_executable_path="/opt/game/bin/game",
            command="/proc/self/exe",
        )
        self.assertEqual(process.executable_name, "game")


class IgnoreTests(unittest.TestCase):
    def test_kernel_thread_is_ignored(self):
        self.assertTrue(should_ignore(make_process(1, "kworker/0:1", name="kworker")))

    def test_wine_helper_is_ignored(self):
        process = make_process(1, "C:\\windows\\system32\\winedevice.exe")
        self.assertTrue(should_ignore(process))

    def test_game_is_not_ignored(self):
        process = make_process(1, r"C:\Games\World_of_Tanks_NA\win64\WorldOfTanks.exe")
        self.assertFalse(should_ignore(process))


class DeduplicateTests(unittest.TestCase):
    def test_collapses_identical_name_and_command(self):
        a = make_process(1, "/usr/bin/game", name="game")
        b = make_process(2, "/usr/bin/game", name="game")
        self.assertEqual(len(deduplicate([a, b])), 1)

    def test_keeps_distinct_commands(self):
        a = make_process(1, "/usr/bin/game --one", name="game")
        b = make_process(2, "/usr/bin/game --two", name="game")
        self.assertEqual(len(deduplicate([a, b])), 2)


class ReadProcessTests(unittest.TestCase):
    def test_reads_a_real_process(self):
        process = read_process(Path(f"/proc/{os.getpid()}"))
        self.assertIsNotNone(process)
        self.assertEqual(process.pid, os.getpid())

    def test_missing_pid_returns_none(self):
        self.assertIsNone(read_process(Path("/proc/999999999")))

    def test_non_numeric_entry_returns_none(self):
        self.assertIsNone(read_process(Path("/proc/self")))


class DetectTests(unittest.TestCase):
    def setUp(self):
        self.wot = Profile(name="world-of-tanks", games=(Game("WorldOfTanks.exe"),))
        self.desktop = Profile(name="desktop")

    def test_matches_configured_game(self):
        process = make_process(42, r"C:\Games\World_of_Tanks_NA\win64\WorldOfTanks.exe")
        detection = detect([self.desktop, self.wot], processes=[process])
        self.assertIsNotNone(detection.game)
        self.assertEqual(detection.game.profile.name, "world-of-tanks")
        self.assertEqual(detection.game.process.pid, 42)

    def test_match_is_case_insensitive(self):
        process = make_process(42, r"C:\Games\worldoftanks.EXE")
        detection = detect([self.wot], processes=[process])
        self.assertIsNotNone(detection.game)

    def test_no_match_returns_none(self):
        process = make_process(42, "/usr/bin/firefox")
        detection = detect([self.wot], processes=[process])
        self.assertIsNone(detection.game)
        self.assertEqual(len(detection.rejections), 1)

    def test_launcher_does_not_match(self):
        launcher = make_process(1, "/usr/bin/umu-run", name="umu-run")
        detection = detect([self.wot], processes=[launcher])
        self.assertIsNone(detection.game)

    def test_first_profile_in_order_wins(self):
        other = Profile(name="other", games=(Game("WorldOfTanks.exe"),))
        process = make_process(42, r"C:\Games\World_of_Tanks_NA\win64\WorldOfTanks.exe")
        detection = detect([self.wot, other], processes=[process])
        self.assertEqual(detection.game.profile.name, "world-of-tanks")

    def test_no_games_configured_rejects_everything(self):
        process = make_process(42, "/usr/bin/firefox")
        detection = detect([self.desktop], processes=[process])
        self.assertIsNone(detection.game)
        self.assertEqual(detection.rejections[0].reason, "no games configured")

    def test_explain_records_rejection_reason(self):
        process = make_process(42, "/usr/bin/firefox")
        detection = detect([self.wot], processes=[process])
        self.assertIn("firefox", detection.rejections[0].reason)


class DiscoverProcessesTests(unittest.TestCase):
    def test_finds_at_least_this_process(self):
        processes = discover_processes()
        self.assertTrue(processes)
        self.assertTrue(all(p.pid > 0 for p in processes))


if __name__ == "__main__":
    unittest.main()
