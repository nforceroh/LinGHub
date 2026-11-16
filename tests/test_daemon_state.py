"""Tests for the daemon's profile-selection state machine."""

import unittest

from linghub.config import Config
from linghub.daemon.state import DaemonState
from linghub.discovery.detector import Detection, Match, Rejection
from linghub.discovery.processes import ProcessInfo
from linghub.domain.profile import Binding, Game, Profile


def make_config(*profiles: Profile, desktop: str = "desktop") -> Config:
    return Config(profiles=list(profiles), desktop_profile=desktop, poll_interval=2.0)


def make_process(pid: int, argv0: str) -> ProcessInfo:
    return ProcessInfo(pid=pid, name="p", executable_path=argv0,
                       real_executable_path=argv0, command=argv0)


def detection_for(*profiles: Profile) -> Detection:
    matches = [
        Match(game=profile.games[0], profile=profile, process=make_process(i, profile.games[0].executable))
        for i, profile in enumerate(profiles)
    ]
    return Detection(matches=matches, rejections=[], considered=len(matches))


DESKTOP = Profile(name="desktop")
WOT = Profile(name="world-of-tanks", games=(Game("WorldOfTanks.exe"),))
SC = Profile(name="star-citizen", games=(Game("StarCitizen.exe"),))


class TargetProfileTests(unittest.TestCase):
    def test_empty_stack_targets_desktop(self):
        state = DaemonState(config=make_config(DESKTOP, WOT))
        self.assertEqual(state.target_profile.name, "desktop")

    def test_stack_top_wins(self):
        state = DaemonState(config=make_config(DESKTOP, WOT, SC))
        state.stack = ["world-of-tanks", "star-citizen"]
        self.assertEqual(state.target_profile.name, "star-citizen")

    def test_missing_desktop_raises(self):
        state = DaemonState(config=make_config(WOT, desktop="nope"))
        with self.assertRaisesRegex(RuntimeError, "desktop profile 'nope' is missing"):
            state.target_profile


class ObserveTests(unittest.TestCase):
    def test_game_start_pushes_onto_stack(self):
        state = DaemonState(config=make_config(DESKTOP, WOT))
        state.observe(detection_for(WOT))
        self.assertEqual(state.stack, ["world-of-tanks"])

    def test_game_exit_clears_stack(self):
        state = DaemonState(config=make_config(DESKTOP, WOT))
        state.observe(detection_for(WOT))
        state.observe(Detection())
        self.assertEqual(state.stack, [])

    def test_repeated_detection_does_not_duplicate(self):
        state = DaemonState(config=make_config(DESKTOP, WOT))
        state.observe(detection_for(WOT))
        state.observe(detection_for(WOT))
        self.assertEqual(state.stack, ["world-of-tanks"])

    def test_nested_games_stack(self):
        state = DaemonState(config=make_config(DESKTOP, WOT, SC))
        state.observe(detection_for(WOT))
        state.observe(detection_for(WOT, SC))
        self.assertEqual(state.stack, ["world-of-tanks", "star-citizen"])

    def test_out_of_order_exit_does_not_strand_stack(self):
        state = DaemonState(config=make_config(DESKTOP, WOT, SC))
        state.observe(detection_for(WOT, SC))
        # WoT exits while SC keeps running; the stack must drop WoT only.
        state.observe(detection_for(SC))
        self.assertEqual(state.stack, ["star-citizen"])

    def test_unknown_profile_in_stack_is_dropped(self):
        state = DaemonState(config=make_config(DESKTOP, WOT))
        state.stack = ["deleted-profile"]
        state.observe(Detection())
        self.assertEqual(state.stack, [])


class NeedsWriteTests(unittest.TestCase):
    def test_write_needed_when_nothing_loaded(self):
        state = DaemonState(config=make_config(DESKTOP, WOT))
        self.assertTrue(state.needs_write)

    def test_no_write_when_target_already_loaded(self):
        state = DaemonState(config=make_config(DESKTOP, WOT))
        state.mark_loaded("desktop")
        self.assertFalse(state.needs_write)

    def test_write_needed_when_game_starts(self):
        state = DaemonState(config=make_config(DESKTOP, WOT))
        state.mark_loaded("desktop")
        state.observe(detection_for(WOT))
        self.assertTrue(state.needs_write)

    def test_no_write_when_game_exits_back_to_loaded_desktop(self):
        state = DaemonState(config=make_config(DESKTOP, WOT))
        state.mark_loaded("desktop")
        state.observe(detection_for(WOT))
        state.observe(Detection())
        self.assertFalse(state.needs_write)


if __name__ == "__main__":
    unittest.main()


class SetBindingTests(unittest.TestCase):
    """Changing a binding must invalidate the loaded fingerprint.

    Otherwise the daemon believes the mouse already has the right profile and
    never writes the change.
    """

    def setUp(self):
        self.binding = Binding(type="key", value="KEY_F")
        self.state = DaemonState(config=make_config(
            DESKTOP,
            Profile(name="wot", bindings={3: self.binding}),
        ))
        # Pretend the game is running, so "wot" is the target profile.
        self.state.stack = ["wot"]
        self.state.mark_loaded("wot")

    def test_set_binding_reports_success(self):
        self.assertTrue(
            self.state.set_binding("wot", 5, Binding(type="special", value="resolution-up"))
        )

    def test_set_binding_updates_the_profile(self):
        self.state.set_binding("wot", 5, Binding(type="special", value="resolution-up"))
        profile = self.state.config.profile_named("wot")
        self.assertEqual(profile.bindings[5].type, "special")

    def test_set_binding_leaves_other_bindings_alone(self):
        self.state.set_binding("wot", 5, Binding(type="special", value="resolution-up"))
        self.assertEqual(self.state.config.profile_named("wot").bindings[3], self.binding)

    def test_set_binding_marks_the_loaded_profile_stale(self):
        self.assertFalse(self.state.needs_write)
        self.state.set_binding("wot", 5, Binding(type="special", value="resolution-up"))
        self.assertTrue(self.state.needs_write)

    def test_removing_a_binding_also_marks_it_stale(self):
        self.state.set_binding("wot", 3, None)
        self.assertNotIn(3, self.state.config.profile_named("wot").bindings)
        self.assertTrue(self.state.needs_write)

    def test_unknown_profile_returns_false(self):
        self.assertFalse(self.state.set_binding("nope", 3, self.binding))

    def test_unknown_profile_leaves_the_config_alone(self):
        before = self.state.config
        self.state.set_binding("nope", 3, self.binding)
        self.assertIs(self.state.config, before)


class BindingPersistenceTests(unittest.TestCase):
    """A binding change must survive a save/load cycle.

    The daemon updates the config in memory and then writes it. If the two
    disagree, the mouse gets one thing and the file another.
    """

    def test_change_survives_a_roundtrip(self):
        import json
        import tempfile
        from pathlib import Path

        from linghub.config import load, save

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({
                "version": 1,
                "settings": {"desktop_profile": "desktop"},
                "profiles": {
                    "desktop": {"games": []},
                    "wot": {"games": ["WorldOfTanks.exe"],
                            "bindings": {"3": {"type": "key", "value": "KEY_F"}}},
                },
            }), encoding="utf-8")

            state = DaemonState(config=load(path))
            state.stack = ["wot"]
            state.mark_loaded("wot")
            self.assertFalse(state.needs_write)

            self.assertTrue(state.set_binding("wot", 5, Binding("special", "resolution-up")))
            save(path, state.config)

            # The mouse must be told to rewrite, not left thinking it is current.
            self.assertTrue(state.needs_write)

            reloaded = load(path)
            self.assertEqual(reloaded.profile_named("wot").bindings[5].type, "special")
            self.assertEqual(reloaded.profile_named("wot").bindings[3].type, "key")

    def test_desktop_profile_change_also_rewrites(self):
        state = DaemonState(config=make_config(DESKTOP, WOT))
        state.mark_loaded("desktop")
        self.assertFalse(state.needs_write)
        state.set_binding("desktop", 0, Binding("key", "KEY_A"))
        self.assertTrue(state.needs_write)


class DeviceLossTests(unittest.TestCase):
    """A mouse can vanish at any time.

    A KVM switch, a cable, or a flat battery all remove the hidraw node. The
    daemon must survive that, drop its stale writer, and reconnect when the
    device returns - not exit and rely on systemd to restart it.
    """

    def _daemon(self):
        from linghub.daemon.service import Daemon

        daemon = Daemon()
        daemon._state = DaemonState(config=make_config(DESKTOP, WOT))
        daemon._state.mark_loaded("stale")
        return daemon

    def test_a_vanished_device_does_not_escape_the_tick(self):
        import asyncio

        from linghub.hardware.writer import WriteError

        daemon = self._daemon()

        class Vanished:
            async def apply(self, profile, slot):
                raise RuntimeError("D-Bus call Get failed: Unknown object")

        daemon._writer = Vanished()
        # Must return, not raise.
        asyncio.run(daemon._tick())
        self.assertIsNone(daemon._writer, "the stale writer was kept")

    def test_a_write_error_keeps_the_writer(self):
        """A refused write is not the same as a missing device."""
        import asyncio

        from linghub.hardware.writer import WriteError

        daemon = self._daemon()
        writer = type("W", (), {"apply": staticmethod(lambda p, s: None)})()
        daemon._writer = writer

        async def apply(profile, slot):
            raise WriteError("commit did not complete within the timeout")

        daemon._writer = type("W", (), {"apply": staticmethod(apply)})()
        asyncio.run(daemon._tick())
        self.assertIsNotNone(daemon._writer)

    def test_the_daemon_reconnects_after_device_loss(self):
        import asyncio

        from linghub.hardware.ratbag import DeviceNotFound

        daemon = self._daemon()
        attempts = {"n": 0}

        async def connect():
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise DeviceNotFound("no G502 found")
            daemon._writer = object()

        daemon._connect = connect
        asyncio.run(daemon._reconnect(delay=0))
        self.assertEqual(attempts["n"], 3)
        self.assertIsNotNone(daemon._writer)

    def test_a_tick_with_no_device_does_not_raise(self):
        """After a failed reconnect there is nothing to write to; skip, don't crash."""
        import asyncio

        from linghub.hardware.ratbag import DeviceNotFound

        daemon = self._daemon()

        async def never():
            raise DeviceNotFound("still gone")

        daemon._connect = never
        daemon._writer = None
        asyncio.run(daemon._tick())
        self.assertIsNone(daemon._writer)

    def test_reconnect_gives_up_so_detection_continues(self):
        """Blocking until the device returns would stop detecting games."""
        import asyncio

        from linghub.hardware.ratbag import DeviceNotFound

        daemon = self._daemon()

        async def never():
            raise DeviceNotFound("still gone")

        daemon._connect = never
        asyncio.run(daemon._reconnect(attempts=2, delay=0))
        self.assertIsNone(daemon._writer)


class ResolutionTests(unittest.TestCase):
    """DPI slots and the report rate are part of the profile, like bindings."""

    def _state(self):
        return DaemonState(config=make_config(
            DESKTOP,
            Profile(name="wot", resolutions=(
                {"dpi": 400}, {"dpi": 800, "default": True}, {"dpi": 1600},
            )),
        ))

    def test_set_resolution_updates_one_slot(self):
        state = self._state()
        self.assertTrue(state.set_resolution("wot", 2, 3200))
        self.assertEqual(state.config.profile_named("wot").resolutions[2]["dpi"], 3200)

    def test_set_resolution_leaves_other_slots_alone(self):
        state = self._state()
        state.set_resolution("wot", 2, 3200)
        self.assertEqual(state.config.profile_named("wot").resolutions[0]["dpi"], 400)

    def test_moving_the_default_clears_the_old_one(self):
        """Two defaults would be ambiguous, and the hardware honours one."""
        state = self._state()
        state.set_resolution("wot", 0, 400, make_default=True)
        resolutions = state.config.profile_named("wot").resolutions
        self.assertTrue(resolutions[0].get("default"))
        self.assertFalse(resolutions[1].get("default"))

    def test_disabling_a_slot_is_recorded(self):
        state = self._state()
        state.set_resolution("wot", 2, 1600, disabled=True)
        self.assertTrue(state.config.profile_named("wot").resolutions[2]["disabled"])

    def test_set_resolution_rejects_a_missing_slot(self):
        state = self._state()
        self.assertFalse(state.set_resolution("wot", 9, 800))

    def test_set_resolution_rejects_an_unknown_profile(self):
        self.assertFalse(self._state().set_resolution("nope", 0, 800))

    def test_set_report_rate(self):
        state = self._state()
        self.assertTrue(state.set_report_rate("wot", 500))
        self.assertEqual(state.config.profile_named("wot").report_rate, 500)

    def test_changing_dpi_makes_the_profile_stale(self):
        """Otherwise the daemon never pushes it to the mouse."""
        state = self._state()
        state.stack = ["wot"]
        state.mark_loaded("wot")
        self.assertFalse(state.needs_write)
        state.set_resolution("wot", 0, 999)
        self.assertTrue(state.needs_write)

    def test_changing_report_rate_makes_the_profile_stale(self):
        state = self._state()
        state.stack = ["wot"]
        state.mark_loaded("wot")
        state.set_report_rate("wot", 125)
        self.assertTrue(state.needs_write)


class FingerprintTests(unittest.TestCase):
    """Editing a profile's contents must trigger a rewrite, not just a rename."""

    def _config(self, bindings):
        profile = Profile(name="desktop", bindings=bindings)
        return make_config(profile)

    def test_editing_bindings_triggers_rewrite(self):
        state = DaemonState(config=self._config({0: Binding("button", 1)}))
        state.mark_loaded("desktop")
        self.assertFalse(state.needs_write)

        state.config = self._config({0: Binding("button", 2)})
        self.assertTrue(state.needs_write)

    def test_editing_report_rate_triggers_rewrite(self):
        state = DaemonState(config=make_config(Profile(name="desktop", report_rate=1000)))
        state.mark_loaded("desktop")
        state.config = make_config(Profile(name="desktop", report_rate=500))
        self.assertTrue(state.needs_write)

    def test_editing_leds_triggers_rewrite(self):
        state = DaemonState(config=make_config(Profile(name="desktop", leds=({"index": 0, "mode": "on"},))))
        state.mark_loaded("desktop")
        state.config = make_config(Profile(name="desktop", leds=({"index": 0, "mode": "off"},)))
        self.assertTrue(state.needs_write)

    def test_identical_config_does_not_trigger_rewrite(self):
        state = DaemonState(config=self._config({0: Binding("button", 1)}))
        state.mark_loaded("desktop")
        state.config = self._config({0: Binding("button", 1)})
        self.assertFalse(state.needs_write)

    def test_binding_order_does_not_trigger_rewrite(self):
        state = DaemonState(config=self._config({0: Binding("button", 1), 1: Binding("button", 2)}))
        state.mark_loaded("desktop")
        state.config = self._config({1: Binding("button", 2), 0: Binding("button", 1)})
        self.assertFalse(state.needs_write)
