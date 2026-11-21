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
from linghub.hardware.failures import LoadRefused, MouseAbsent, MouseLost, MouseMisconfigured
from linghub.hardware.mouse import Connected

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
        self.attempts = 0
        # What the next active-slot read does: None answers, or raises this.
        self.next_read: Exception | None = None

    async def apply(self, profile, slot):
        self.attempts += 1
        if self.next_write is not None:
            error, self.next_write = self.next_write, None
            raise error
        self.written.append((profile.name, slot))
        self.active = slot
        return type("Result", (), {"changed": ()})()

    async def active_slot(self):
        if self.next_read is not None:
            error, self.next_read = self.next_read, None
            raise error
        return self.active



class FakeConnector:
    """Hands out a mouse with its capabilities, or raises while absent."""

    def __init__(self, mouse: FakeMouse | None = None):
        self.mouse = mouse or FakeMouse()
        self.present = True
        self.connects = 0
        # Raised by every connect while set: ratbagd not answering, say.
        self.error: Exception | None = None
        # What the next connect does after finding the mouse: None succeeds,
        # or the exception to raise. A mouse that vanishes mid-connect.
        self.next_connect_error: Exception | None = None

    async def connect(self):
        self.connects += 1
        if self.error is not None:
            raise self.error
        if not self.present:
            raise MouseAbsent("no G502 found")
        if self.next_connect_error is not None:
            error, self.next_connect_error = self.next_connect_error, None
            raise error
        return Connected(self.mouse, [125, 250, 500, 1000])

    def disconnect(self):
        pass


class FakeNotifier:
    """Records desktop notifications instead of sending them."""

    available = True

    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    async def connect(self):
        return True

    async def notify(self, summary, body, tag=None):
        self.sent.append((summary, body))

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
        self.now = 1000.0
        self.notifier = FakeNotifier()
        self.daemon = Daemon(
            config_path=self.path,
            detector=lambda _profiles: self.detection,
            mouse=self.mouse,
            announce=self.announced,
            clock=lambda: self.now,
            notifier=self.notifier,
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

    def test_the_view_reports_the_game_and_the_loaded_profile(self):
        h = DaemonHarness(self)
        h.detection = running(WOT)
        h.tick()
        snapshot = h.daemon.view().state
        self.assertEqual(snapshot.detected_game, "world-of-tanks")
        self.assertEqual(snapshot.loaded_profile, "world-of-tanks")

    def test_the_desktop_profile_is_reported_before_the_first_tick(self):
        """The tray showed "unknown" after a reboot until the daemon wrote.

        Clients read the view as soon as the daemon publishes it, which is
        before the first tick, so the desktop profile has to be named then.
        """
        h = DaemonHarness(self)
        self.assertEqual(h.daemon.view().state.loaded_profile, "desktop")

    def test_the_first_tick_still_writes_despite_the_assumption(self):
        """Naming the desktop profile must not skip the startup write, which
        is what picks up config edits made while the daemon was stopped."""
        h = DaemonHarness(self)
        h.tick()
        self.assertEqual(h.written, [("desktop", 0)])


class DriftTests(unittest.TestCase):
    """Something outside the daemon moved the mouse to another slot."""

    def test_a_moved_slot_is_written_again(self):
        h = DaemonHarness(self)
        h.detection = running(WOT)
        h.tick()
        h.mouse.mouse.active = 0  # a physical profile button, say
        h.tick()
        self.assertEqual(h.written, [("world-of-tanks", 1), ("world-of-tanks", 1)])

    def test_an_unknown_slot_is_neither_drift_nor_a_lost_mouse(self):
        """A sleeping mouse cannot say which slot it is on (#2).

        Reloading would be a guess, and reconnecting every two seconds while
        it sleeps would be churn. The next answer decides.
        """
        from linghub.hardware.active_slot import SlotUnknown

        h = DaemonHarness(self)
        h.tick()
        h.mouse.mouse.active = 1          # drifted, but the read cannot say so
        h.mouse.mouse.next_read = SlotUnknown("no reply")
        h.tick()
        self.assertEqual(h.written, [("desktop", 0)], "an unknown slot caused a reload")
        self.assertEqual(h.mouse.connects, 1, "an unknown slot caused a reconnect")
        h.tick()                          # the mouse answers again
        self.assertEqual(h.written, [("desktop", 0), ("desktop", 0)])


class MouseLossTests(unittest.TestCase):
    """A mouse can vanish at any time.

    A KVM switch, a cable, or a flat battery all remove the hidraw node. The
    daemon must survive that, drop the stale mouse, and reconnect when it
    returns - not exit and rely on systemd to restart it.
    """

    def test_a_vanished_mouse_is_reconnected_on_the_next_tick(self):
        h = DaemonHarness(self)
        h.mouse.mouse.next_write = MouseLost("D-Bus call Get failed: Unknown object")
        h.tick()  # must return, not raise
        self.assertEqual(h.written, [])
        h.tick()
        self.assertEqual(h.mouse.connects, 2, "the stale mouse was kept")
        self.assertEqual(h.written, [("desktop", 0)])

    def test_a_mouse_lost_during_connect_is_an_absence_not_a_bug(self):
        """A KVM flick while connecting is a lost mouse, not a daemon bug.

        The connector raises MouseLost when the mouse vanishes before its
        capabilities are read. _reconnect treats that as an absence: it warns
        once, instead of tick's blanket handler logging a traceback.
        """
        h = DaemonHarness(self)
        h.mouse.next_connect_error = MouseLost("vanished while connecting")
        with self.assertLogs("linghub.daemon", "DEBUG") as logs:
            h.tick()
        errors = [r.getMessage() for r in logs.records if r.levelname == "ERROR"]
        self.assertEqual(errors, [], "a lost mouse was logged as a daemon bug")
        warnings = [r.getMessage() for r in logs.records if r.levelname == "WARNING"]
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn("vanished while connecting", warnings[0])
        self.assertEqual(h.written, [], "nothing to write to while the mouse is away")

        h.tick()
        self.assertEqual(h.written, [("desktop", 0)], "the next check did not reconnect")

    def test_a_refused_load_keeps_the_mouse(self):
        """A refused load is not a missing mouse: no reconnect."""
        h = DaemonHarness(self)
        h.mouse.mouse.next_write = LoadRefused("commit did not complete within the timeout")
        h.tick()
        h.tick()
        self.assertEqual(h.mouse.connects, 1)

    def test_a_replaced_mouse_is_reconnected_when_a_write_finds_it(self):
        """A reused hidraw path names another device: reconnect, do not retry."""
        h = DaemonHarness(self)
        h.mouse.mouse.next_write = MouseLost("now Logitech Candy")
        h.tick()
        h.tick()
        self.assertEqual(h.mouse.connects, 2, "the stale mouse was kept")
        self.assertEqual(h.written, [("desktop", 0)])

    def test_a_replaced_mouse_is_reconnected_when_a_read_finds_it(self):
        """With nothing to write, the slot read is the only thing that looks."""
        h = DaemonHarness(self)
        h.tick()
        self.assertEqual(h.mouse.connects, 1)
        h.mouse.mouse.next_read = MouseLost("now Logitech Candy")
        h.tick()
        h.tick()
        self.assertEqual(h.mouse.connects, 2, "the stale mouse was kept")

    def test_a_vanished_path_is_reconnected_without_waiting_for_a_write(self):
        """After a KVM switch the old hidraw path may name nothing at all.

        With nothing to write, the slot read is the only call that touches
        the mouse, so its failure must drop the stale mouse; otherwise the
        daemon stays blind until the next game starts or stops.
        """
        h = DaemonHarness(self)
        h.tick()
        self.assertEqual(h.mouse.connects, 1)
        h.mouse.mouse.next_read = MouseLost(
            "D-Bus call Get failed: Unknown object '/org/freedesktop/ratbag1/device/hidraw12'"
        )
        h.tick()
        self.assertEqual(h.mouse.connects, 2, "the stale mouse was kept")
        self.assertEqual(h.written, [("desktop", 0)], "a reconnect alone is not a reason to write")

    def test_an_absent_mouse_does_not_stop_the_tick(self):
        """Blocking until the mouse returns would stop detecting games."""
        h = DaemonHarness(self)
        h.mouse.present = False
        h.tick()  # must return, not raise
        self.assertEqual(h.mouse.connects, 1, "one attempt per check (#4)")
        self.assertEqual(h.written, [])

    def test_a_mouse_that_appears_later_gets_the_profile(self):
        h = DaemonHarness(self)
        h.mouse.present = False
        h.tick()
        h.mouse.present = True
        h.tick()
        self.assertEqual(h.written, [("desktop", 0)])



class AbsenceTests(unittest.TestCase):
    """While the mouse is away, checks keep their pace and the log stays quiet (#4).

    A KVM switch can leave the mouse on another machine for minutes. Sleeping
    between retries inside a check slowed detection to about 8 s and held
    back GameMode wake-ups; logging every check filled the journal.
    """

    def _absent(self, h):
        """Connect once, then lose the mouse the way a KVM switch does."""
        h.tick()
        h.mouse.mouse.next_read = MouseLost("D-Bus call Get failed: Unknown object")
        h.mouse.present = False

    def _logs(self, level="DEBUG"):
        return self.assertLogs("linghub.daemon", level)

    @staticmethod
    def _at(logs, level):
        return [r.getMessage() for r in logs.records if r.levelname == level]

    def test_each_check_makes_one_attempt_and_never_sleeps(self):
        from unittest import mock

        h = DaemonHarness(self)
        self._absent(h)
        with mock.patch("asyncio.sleep", side_effect=AssertionError("slept in a check")):
            for _ in range(3):
                h.tick()
        self.assertEqual(h.mouse.connects, 4, "the first connect, then one per check")

    def test_one_absence_logs_two_warnings_and_one_back_line(self):
        h = DaemonHarness(self)
        self._absent(h)
        with self._logs() as logs:
            for _ in range(6):
                h.tick()
            h.mouse.present = True
            h.tick()
        warnings = self._at(logs, "WARNING")
        self.assertEqual(len(warnings), 2, warnings)
        self.assertIn("lost the device", warnings[0])
        self.assertIn("no G502 found", warnings[1])
        backs = [m for m in self._at(logs, "INFO") if "device is back" in m]
        self.assertEqual(len(backs), 1, logs.output)

    def test_the_back_line_says_how_long_the_mouse_was_away(self):
        h = DaemonHarness(self)
        self._absent(h)
        h.tick()                      # lost at t=1000
        h.now += 192
        h.mouse.present = True
        with self._logs("INFO") as logs:
            h.tick()
        self.assertIn("device is back after 3m 12s", "\n".join(logs.output))

    def test_a_second_absence_warns_again(self):
        h = DaemonHarness(self)
        self._absent(h)
        h.tick()
        h.mouse.present = True
        h.tick()                      # back
        h.mouse.mouse.next_read = MouseLost("D-Bus call Get failed: Unknown object")
        h.mouse.present = False
        with self._logs("WARNING") as logs:
            h.tick()
            h.tick()
        self.assertEqual(len(logs.records), 2, logs.output)

    def test_a_mouse_missing_at_startup_warns_once_and_has_no_back_line(self):
        """At startup the connector's "found ..." line is the "back" line."""
        h = DaemonHarness(self)
        h.mouse.present = False
        with self._logs() as logs:
            for _ in range(4):
                h.tick()
            h.mouse.present = True
            h.tick()
        self.assertEqual(len(self._at(logs, "WARNING")), 1, logs.output)
        self.assertFalse(any("device is back" in m for m in self._at(logs, "INFO")))
        self.assertEqual(h.written, [("desktop", 0)])

    def test_ratbagd_down_is_an_absence_not_a_failed_check(self):
        h = DaemonHarness(self)
        h.mouse.error = MouseAbsent(
            "cannot reach the mouse through ratbagd: org.freedesktop.DBus.Error.ServiceUnknown"
        )
        with self._logs() as logs:
            for _ in range(4):
                h.tick()
        self.assertEqual(self._at(logs, "ERROR"), [], "a check failed outright")
        warnings = self._at(logs, "WARNING")
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn("ratbagd", warnings[0])

    def test_the_mouse_is_found_on_the_check_after_it_returns(self):
        h = DaemonHarness(self)
        self._absent(h)
        h.tick()
        h.tick()
        h.mouse.present = True
        before = h.mouse.connects
        h.tick()
        self.assertEqual(h.mouse.connects, before + 1)
        self.assertEqual(h.written[-1], ("desktop", 0))



class RefusedLoadTests(unittest.TestCase):
    """A refused load is said once and not retried until something changes (#8).

    It used to be retried every check with an ERROR each time, and each
    retry could rewrite the mouse's flash.
    """

    def _refusing(self):
        h = DaemonHarness(self)
        h.mouse.mouse.next_write = LoadRefused("unknown key name 'KEY_BOGUS'")
        return h

    def test_a_refused_load_is_not_retried(self):
        h = self._refusing()
        for _ in range(4):
            h.tick()
        self.assertEqual(h.written, [])
        self.assertEqual(h.mouse.mouse.attempts, 1, "retried a refused load")

    def test_it_is_logged_once_and_notified_once(self):
        h = self._refusing()
        with self.assertLogs("linghub.daemon", "ERROR") as logs:
            for _ in range(4):
                h.tick()
        self.assertEqual(len(logs.records), 1, logs.output)
        self.assertIn("KEY_BOGUS", logs.output[0])
        self.assertEqual(len(h.notifier.sent), 1)
        summary, body = h.notifier.sent[0]
        self.assertIn("desktop", summary)
        self.assertIn("KEY_BOGUS", body)

    def test_a_config_change_retries(self):
        h = self._refusing()
        h.tick()
        config_module.save(h.path, Config(
            profiles=[DESKTOP, WOT], desktop_profile="desktop", poll_interval=3.0,
        ))
        h.tick()
        self.assertEqual(h.written, [("desktop", 0)])

    def test_a_reconnect_retries(self):
        h = self._refusing()
        h.tick()
        h.mouse.mouse.next_read = MouseLost("unplugged")
        h.tick()                       # lost, reconnects in the same check, retries
        self.assertEqual(h.written, [("desktop", 0)])

    def test_a_different_target_is_loaded(self):
        h = self._refusing()
        h.tick()
        h.detection = running(WOT)
        h.tick()
        self.assertEqual(h.written, [("world-of-tanks", 1)])


class MisconfiguredTests(unittest.TestCase):
    def test_a_misconfiguration_is_one_error_naming_it(self):
        h = DaemonHarness(self)
        h.mouse.error = MouseMisconfigured("multiple G502 devices found; unplug one")
        with self.assertLogs("linghub.daemon", "DEBUG") as logs:
            for _ in range(4):
                h.tick()
        errors = [r.getMessage() for r in logs.records if r.levelname == "ERROR"]
        self.assertEqual(len(errors), 1, logs.output)
        self.assertIn("multiple G502", errors[0])
        self.assertFalse(any(r.levelname == "WARNING" for r in logs.records), logs.output)
        self.assertEqual(h.mouse.connects, 4, "keeps checking: it may resolve itself")


class BugTests(unittest.TestCase):
    """An error the seam doesn't name is a bug: logged, survived (#8)."""

    def test_a_stray_error_from_the_mouse_does_not_stop_the_daemon(self):
        h = DaemonHarness(self)

        async def broken(profile, slot):
            raise ValueError("a bug in the adapter")

        h.mouse.mouse.apply = broken
        with self.assertLogs("linghub.daemon", "ERROR") as logs:
            for _ in range(3):
                h.tick()             # must return, not raise
        self.assertEqual(len(logs.records), 1, "logged once per distinct error")
        self.assertIsNotNone(logs.records[0].exc_info, "logged with its traceback")
        self.assertIn("a bug in the adapter", logs.output[0])


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
        self.assertIn("world-of-tanks", h.daemon.view().state.profile_names)

    def test_a_valid_edit_is_picked_up(self):
        h = DaemonHarness(self)
        h.tick()
        config_module.save(h.path, Config(
            profiles=[DESKTOP], desktop_profile="desktop", poll_interval=2.0,
        ))
        h.tick()
        self.assertEqual(h.daemon.view().state.profile_names, ("desktop",))


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

    def test_startup_survives_ratbagd_being_down(self):
        """It used to catch only DeviceNotFound, so ratbagd being down
        stopped the daemon before it detected anything (#4)."""
        h = DaemonHarness(self)
        h.mouse.error = MouseAbsent("cannot reach the mouse through ratbagd: ServiceUnknown")

        async def nothing():
            pass

        h.daemon._export_interface = nothing
        h.daemon._start_notifications = nothing

        def stop(_profiles):
            raise KeyboardInterrupt

        h.daemon._detector = stop
        with self.assertRaises(KeyboardInterrupt):  # reached detection
            asyncio.run(h.daemon.run())


if __name__ == "__main__":
    unittest.main()
