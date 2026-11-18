"""Tests for the daemon, through its constructor and one tick at a time.

The mouse and detection are injected, so these run without a bus, a device,
or /proc: a fake mouse records what was written and can vanish, refuse a
write, or report that something else moved the active slot.
"""

import asyncio
import tempfile
import unittest
from pathlib import Path

from linghub import config as config_module
from linghub.config import Config
from linghub.daemon.service import Daemon
from linghub.discovery.detector import Detection, Match
from linghub.discovery.processes import ProcessInfo
from linghub.domain.profile import Game, Profile
from linghub.hardware.ratbag import DeviceNotFound

DESKTOP = Profile(name="desktop")
WOT = Profile(name="world-of-tanks", games=(Game("WorldOfTanks.exe"),))


def running(*profiles: Profile) -> Detection:
    matches = [
        Match(
            game=profile.games[0],
            profile=profile,
            process=ProcessInfo(pid=i, name="p", executable_path=profile.games[0].executable,
                                real_executable_path=profile.games[0].executable,
                                command=profile.games[0].executable),
        )
        for i, profile in enumerate(profiles)
    ]
    return Detection(matches=matches, rejections=[], considered=len(matches))


class FakeMouse:
    """A mouse that records writes, and remembers the slot last written."""

    def __init__(self):
        self.written: list[tuple[str, int]] = []
        self.active: int | None = None
        # What the next write does: None succeeds, or the exception to raise.
        self.next_write: Exception | None = None

    async def apply(self, profile, slot):
        if self.next_write is not None:
            error, self.next_write = self.next_write, None
            raise error
        self.written.append((profile.name, slot))
        self.active = slot
        return type("Result", (), {"changed": ()})()

    async def active_slot(self):
        return self.active

    async def report_rates(self):
        return [125, 250, 500, 1000]


class FakeConnector:
    """Hands out a mouse, or raises DeviceNotFound while `present` is False."""

    def __init__(self, mouse: FakeMouse | None = None):
        self.mouse = mouse or FakeMouse()
        self.present = True
        self.connects = 0

    async def connect(self):
        self.connects += 1
        if not self.present:
            raise DeviceNotFound("no G502 found")
        return self.mouse

    def disconnect(self):
        pass


class Recorder:
    """An announcer that remembers what the daemon announced, in order."""

    def __init__(self):
        self.events: list[tuple[str, ...]] = []

    def profile_loaded(self, name):
        self.events.append(("profile_loaded", name))

    def game_started(self, name):
        self.events.append(("game_started", name))

    def game_stopped(self, name):
        self.events.append(("game_stopped", name))

    def config_changed(self):
        self.events.append(("config_changed",))


class DaemonHarness:
    """A daemon over a temp config, with what is running set by the test."""

    def __init__(self, case: unittest.TestCase, *profiles: Profile):
        directory = tempfile.TemporaryDirectory()
        case.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "config.json"
        config_module.save(self.path, Config(
            profiles=list(profiles or (DESKTOP, WOT)),
            desktop_profile="desktop",
            poll_interval=2.0,
        ))
        self.detection = running()
        self.mouse = FakeConnector()
        self.announced = Recorder()
        self.daemon = Daemon(
            config_path=self.path,
            detector=lambda _profiles: self.detection,
            mouse=self.mouse,
            announce=self.announced,
            reconnect_delay=0,
        )
        case.assertTrue(self.daemon.load_config())

    def tick(self):
        asyncio.run(self.daemon.tick())

    @property
    def written(self):
        return self.mouse.mouse.written


class WhatGetsWrittenTests(unittest.TestCase):
    """ADR-0001, at the point where it reaches the hardware."""

    def test_a_running_game_loads_its_profile_into_slot_1(self):
        h = DaemonHarness(self)
        h.detection = running(WOT)
        h.tick()
        self.assertEqual(h.written, [("world-of-tanks", 1)])

    def test_with_no_game_the_desktop_profile_goes_to_slot_0(self):
        h = DaemonHarness(self)
        h.tick()
        self.assertEqual(h.written, [("desktop", 0)])

    def test_nothing_is_rewritten_while_nothing_changes(self):
        h = DaemonHarness(self)
        h.tick()
        h.tick()
        self.assertEqual(h.written, [("desktop", 0)])

    def test_a_manual_load_reaches_the_mouse(self):
        h = DaemonHarness(self)
        h.tick()
        self.assertTrue(h.daemon.profiles.load("world-of-tanks"))
        h.tick()
        self.assertEqual(h.written[-1], ("world-of-tanks", 1))

    def test_the_snapshot_reports_the_game_and_the_loaded_profile(self):
        h = DaemonHarness(self)
        h.detection = running(WOT)
        h.tick()
        snapshot = h.daemon.snapshot()
        self.assertEqual(snapshot.detected_game, "world-of-tanks")
        self.assertEqual(snapshot.loaded_profile, "world-of-tanks")


class DriftTests(unittest.TestCase):
    """Something outside the daemon moved the mouse to another slot."""

    def test_a_moved_slot_is_written_again(self):
        h = DaemonHarness(self)
        h.detection = running(WOT)
        h.tick()
        h.mouse.mouse.active = 0  # a physical profile button, say
        h.tick()
        self.assertEqual(h.written, [("world-of-tanks", 1), ("world-of-tanks", 1)])

    def test_an_unreadable_slot_is_not_drift(self):
        h = DaemonHarness(self)
        h.tick()

        async def unreadable():
            raise RuntimeError("D-Bus call Get failed")

        h.mouse.mouse.active_slot = unreadable
        h.tick()
        self.assertEqual(h.written, [("desktop", 0)])


class MouseLossTests(unittest.TestCase):
    """A mouse can vanish at any time.

    A KVM switch, a cable, or a flat battery all remove the hidraw node. The
    daemon must survive that, drop the stale mouse, and reconnect when it
    returns - not exit and rely on systemd to restart it.
    """

    def test_a_vanished_mouse_is_reconnected_on_the_next_tick(self):
        h = DaemonHarness(self)
        h.mouse.mouse.next_write = RuntimeError("D-Bus call Get failed: Unknown object")
        h.tick()  # must return, not raise
        self.assertEqual(h.written, [])
        h.tick()
        self.assertEqual(h.mouse.connects, 2, "the stale mouse was kept")
        self.assertEqual(h.written, [("desktop", 0)])

    def test_a_refused_write_is_retried_on_the_same_mouse(self):
        """A refused write is not the same as a missing mouse."""
        from linghub.hardware.writer import WriteError

        h = DaemonHarness(self)
        h.mouse.mouse.next_write = WriteError("commit did not complete within the timeout")
        h.tick()
        h.tick()
        self.assertEqual(h.mouse.connects, 1)
        self.assertEqual(h.written, [("desktop", 0)])

    def test_an_absent_mouse_does_not_stop_the_tick(self):
        """Blocking until the mouse returns would stop detecting games."""
        h = DaemonHarness(self)
        h.mouse.present = False
        h.tick()  # must return, not raise
        self.assertEqual(h.mouse.connects, 3, "reconnecting should give up")
        self.assertEqual(h.written, [])

    def test_a_mouse_that_appears_later_gets_the_profile(self):
        h = DaemonHarness(self)
        h.mouse.present = False
        h.tick()
        h.mouse.present = True
        h.tick()
        self.assertEqual(h.written, [("desktop", 0)])


class AnnouncementTests(unittest.TestCase):
    """What the daemon tells its clients, so they never have to poll."""

    def test_a_game_starting_is_announced_before_its_profile_loads(self):
        h = DaemonHarness(self)
        h.tick()
        h.announced.events.clear()
        h.detection = running(WOT)
        h.tick()
        self.assertEqual(h.announced.events, [
            ("game_started", "world-of-tanks"),
            ("profile_loaded", "world-of-tanks"),
        ])

    def test_a_game_stopping_is_announced(self):
        h = DaemonHarness(self)
        h.detection = running(WOT)
        h.tick()
        h.announced.events.clear()
        h.detection = running()
        h.tick()
        self.assertEqual(h.announced.events, [
            ("game_stopped", "world-of-tanks"),
            ("profile_loaded", "desktop"),
        ])

    def test_a_quiet_tick_announces_nothing(self):
        h = DaemonHarness(self)
        h.tick()
        h.announced.events.clear()
        h.tick()
        self.assertEqual(h.announced.events, [])

    def test_a_config_change_is_announced(self):
        h = DaemonHarness(self)
        h.tick()
        h.announced.events.clear()
        self.assertTrue(h.daemon.profiles.create("new", ""))
        self.assertEqual(h.announced.events, [("config_changed",)])

    def test_reloading_an_edited_file_is_announced(self):
        h = DaemonHarness(self)
        h.tick()
        h.announced.events.clear()
        config_module.save(h.path, Config(
            profiles=[DESKTOP], desktop_profile="desktop", poll_interval=2.0,
        ))
        h.tick()
        self.assertIn(("config_changed",), h.announced.events)

    def test_a_broken_edit_is_not_announced(self):
        h = DaemonHarness(self)
        h.tick()
        h.announced.events.clear()
        h.path.write_text(ReloadTests.BROKEN, encoding="utf-8")
        h.tick()
        self.assertEqual(h.announced.events, [])


class ReloadTests(unittest.TestCase):
    """A broken config edit must never take the daemon down.

    A malformed binding raised a bare ValueError from the domain model, which
    escaped, so a single typo in a hand-edited binding killed the service.
    """

    BROKEN = (
        '{"version": 1, "settings": {"desktop_profile": "desktop"},'
        ' "profiles": {"desktop": {"games": [],'
        ' "bindings": {"0": {"type": "nonsense"}}}}}'
    )

    def test_an_invalid_config_is_refused_at_startup(self):
        h = DaemonHarness(self)
        h.path.write_text(self.BROKEN, encoding="utf-8")
        self.assertFalse(h.daemon.load_config())

    def test_a_non_numeric_button_is_refused(self):
        h = DaemonHarness(self)
        h.path.write_text(
            '{"version": 1, "settings": {"desktop_profile": "desktop"},'
            ' "profiles": {"desktop": {"games": [],'
            ' "bindings": {"0": {"type": "button", "value": "left"}}}}}',
            encoding="utf-8",
        )
        self.assertFalse(h.daemon.load_config())

    def test_a_broken_edit_keeps_the_previous_config(self):
        h = DaemonHarness(self)
        h.tick()
        h.path.write_text(self.BROKEN, encoding="utf-8")
        h.tick()  # must return, not raise
        self.assertIn("world-of-tanks", h.daemon.snapshot().profile_names)

    def test_a_valid_edit_is_picked_up(self):
        h = DaemonHarness(self)
        h.tick()
        config_module.save(h.path, Config(
            profiles=[DESKTOP], desktop_profile="desktop", poll_interval=2.0,
        ))
        h.tick()
        self.assertEqual(h.daemon.snapshot().profile_names, ("desktop",))


class StartupTests(unittest.TestCase):
    def test_startup_does_not_require_the_mouse(self):
        """The daemon must be visible to the UI and tray with no mouse present.

        Blocking at startup meant it published nothing and detected nothing for
        as long as the mouse was away - which is normal on a KVM switch.
        """
        h = DaemonHarness(self)
        h.mouse.present = False
        exported = {"n": 0}

        async def export():
            exported["n"] += 1

        async def no_notifications():
            pass

        # The session bus has no second adapter yet, so these two stay patched.
        h.daemon._export_interface = export
        h.daemon._start_notifications = no_notifications

        def stop(_profiles):
            raise KeyboardInterrupt

        h.daemon._detector = stop
        with self.assertRaises(KeyboardInterrupt):
            asyncio.run(h.daemon.run())
        self.assertEqual(exported["n"], 1, "the interface was not published")


if __name__ == "__main__":
    unittest.main()
