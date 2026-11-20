"""Tests for the daemon's profile-selection state machine."""

import unittest

from linghub.config import Config
from linghub.daemon.state import DaemonState
from linghub.discovery.detector import Detection, Match
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


class ResolutionTests(unittest.TestCase):
    """DPI slots and the report rate are part of the profile, like bindings."""

    def _state(self):
        return DaemonState(config=make_config(
            DESKTOP,
            Profile(name="wot", resolutions=(
                {"dpi": 400}, {"dpi": 800, "default": True}, {"dpi": 1600},
            ), leds=({"index": 0, "mode": "on"},)),
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

    def test_set_leds_updates_every_zone(self):
        state = self._state()
        self.assertTrue(state.set_leds("wot", {"mode": "breathing", "brightness": 100}))
        leds = state.config.profile_named("wot").leds
        self.assertTrue(leds)
        for entry in leds:
            self.assertEqual(entry["mode"], "breathing")
            self.assertEqual(entry["brightness"], 100)

    def test_set_leds_rejects_an_unknown_profile(self):
        state = self._state()
        self.assertFalse(state.set_leds("nope", {"mode": "on"}))

    def test_changing_leds_makes_the_profile_stale(self):
        state = self._state()
        state.stack = ["wot"]
        state.mark_loaded("wot")
        self.assertFalse(state.needs_write)
        state.set_leds("wot", {"mode": "off"})
        self.assertTrue(state.needs_write)


class ProfileManagementTests(unittest.TestCase):
    """Creating, renaming and deleting profiles.

    These are structural changes to the config, so the rules that matter are
    about what must never be broken: the desktop profile has to exist, names
    have to stay unique, and the loaded profile must survive a rename.
    """

    def _state(self):
        return DaemonState(config=make_config(DESKTOP, WOT, SC))

    def test_create_adds_a_profile(self):
        state = self._state()
        self.assertTrue(state.create_profile("new-game"))
        self.assertIsNotNone(state.config.profile_named("new-game"))

    def test_create_rejects_a_duplicate_name(self):
        state = self._state()
        self.assertFalse(state.create_profile("world-of-tanks"))
        self.assertEqual(len(state.config.profiles), 3)

    def test_create_rejects_an_empty_name(self):
        self.assertFalse(self._state().create_profile("   "))

    def test_create_with_a_game_records_it(self):
        state = self._state()
        state.create_profile("new-game", executable="NewGame.exe")
        profile = state.config.profile_named("new-game")
        self.assertEqual(profile.games[0].executable, "NewGame.exe")

    def test_create_without_a_game_is_the_desktop_kind(self):
        state = self._state()
        state.create_profile("spare")
        self.assertTrue(state.config.profile_named("spare").is_desktop)

    def test_rename_keeps_the_bindings(self):
        state = self._state()
        state.set_binding("world-of-tanks", 3, Binding("key", "KEY_F"))
        self.assertTrue(state.rename_profile("world-of-tanks", "wot"))
        self.assertEqual(
            state.config.profile_named("wot").bindings[3].value, "KEY_F"
        )

    def test_rename_rejects_an_existing_name(self):
        state = self._state()
        self.assertFalse(state.rename_profile("world-of-tanks", "star-citizen"))

    def test_rename_updates_the_desktop_pointer(self):
        """Otherwise the desktop profile would vanish."""
        state = self._state()
        self.assertTrue(state.rename_profile("desktop", "everyday"))
        self.assertEqual(state.config.desktop_profile, "everyday")
        self.assertIsNotNone(state.config.desktop)

    def test_rename_updates_the_loaded_profile_name(self):
        """Otherwise needs_write would compare against a profile that is gone."""
        state = self._state()
        state.stack = ["world-of-tanks"]
        state.mark_loaded("world-of-tanks")
        state.rename_profile("world-of-tanks", "wot")
        self.assertEqual(state.loaded_profile, "wot")
        self.assertFalse(state.needs_write)

    def test_rename_updates_the_running_games(self):
        state = self._state()
        state.stack = ["world-of-tanks"]
        state.rename_profile("world-of-tanks", "wot")
        self.assertEqual(state.stack, ["wot"])

    def test_delete_removes_a_profile(self):
        state = self._state()
        self.assertTrue(state.delete_profile("star-citizen"))
        self.assertIsNone(state.config.profile_named("star-citizen"))

    def test_delete_refuses_the_desktop_profile(self):
        state = self._state()
        self.assertFalse(state.delete_profile("desktop"))
        self.assertIsNotNone(state.config.profile_named("desktop"))

    def test_delete_refuses_the_last_profile(self):
        state = DaemonState(config=make_config(DESKTOP))
        self.assertFalse(state.delete_profile("desktop"))
        self.assertEqual(len(state.config.profiles), 1)

    def test_delete_drops_it_from_the_stack(self):
        state = self._state()
        state.stack = ["star-citizen"]
        state.mark_loaded("star-citizen")
        state.delete_profile("star-citizen")
        self.assertEqual(state.stack, [])
        self.assertIsNone(state.loaded_profile)


class ActiveSlotTests(unittest.TestCase):
    """The daemon must notice when the hardware disagrees with its belief.

    It used to compare only its own memory, so if the active slot changed
    underneath it - a physical profile button, ratbagctl, a KVM reconnect, or
    ratbagd resetting to a disabled slot - it never corrected itself.
    """

    def _state(self):
        state = DaemonState(config=make_config(DESKTOP, WOT))
        state.stack = ["world-of-tanks"]
        state.mark_loaded("world-of-tanks")
        return state

    def test_no_drift_when_the_expected_slot_is_active(self):
        state = self._state()
        state.observe_active_slot(1)
        self.assertFalse(state.needs_write)

    def test_drift_when_a_different_slot_is_active(self):
        state = self._state()
        state.observe_active_slot(2)
        self.assertTrue(state.needs_write)

    def test_drift_when_nothing_is_active(self):
        state = self._state()
        state.observe_active_slot(None)
        self.assertTrue(state.needs_write)

    def test_the_desktop_profile_expects_slot_0(self):
        state = DaemonState(config=make_config(DESKTOP, WOT))
        state.mark_loaded("desktop")
        state.observe_active_slot(0)
        self.assertFalse(state.needs_write)
        state.observe_active_slot(1)
        self.assertTrue(state.needs_write)

    def test_an_unknown_loaded_profile_is_not_drift(self):
        """Before the first write there is nothing to disagree with.

        needs_write is still true - nothing has been written yet - but that is
        the "never loaded" reason, not drift.
        """
        state = DaemonState(config=make_config(DESKTOP, WOT))
        state.observe_active_slot(3)
        self.assertFalse(state._slot_drifted)

    def test_drift_clears_after_a_successful_write(self):
        state = self._state()
        state.observe_active_slot(2)
        self.assertTrue(state.needs_write)
        state.mark_loaded("world-of-tanks")
        state.observe_active_slot(1)
        self.assertFalse(state.needs_write)


class ManualOverrideTests(unittest.TestCase):
    """A manual override holds until the current game changes.

    It holds with no game running too: a profile loaded by hand at the desktop
    stays loaded until a game starts or another profile is loaded.
    """

    def _state(self):
        return DaemonState(config=make_config(DESKTOP, WOT, SC))

    def test_a_load_with_no_game_running_is_honoured(self):
        state = self._state()
        self.assertTrue(state.request("world-of-tanks"))
        state.observe(detection_for())
        self.assertEqual(state.target_profile.name, "world-of-tanks")

    def test_an_unknown_profile_is_refused(self):
        state = self._state()
        self.assertFalse(state.request("nope"))
        self.assertIsNone(state.manual_override)

    def test_a_game_starting_ends_the_override(self):
        state = self._state()
        state.request("world-of-tanks")
        state.observe(detection_for(SC))
        self.assertIsNone(state.manual_override)
        self.assertEqual(state.target_profile.name, "star-citizen")

    def test_the_override_survives_while_the_same_game_runs(self):
        """Picking a profile mid-game must not be undone by the next tick."""
        state = self._state()
        state.observe(detection_for(WOT))
        state.request("desktop")
        state.observe(detection_for(WOT))
        self.assertEqual(state.target_profile.name, "desktop")

    def test_the_game_exiting_ends_the_override(self):
        state = self._state()
        state.observe(detection_for(WOT))
        state.request("star-citizen")
        state.observe(detection_for())
        self.assertIsNone(state.manual_override)
        self.assertEqual(state.target_profile.name, "desktop")

    def test_the_override_does_not_disturb_the_running_games(self):
        """Ending an override returns to the game that was underneath it."""
        state = self._state()
        state.observe(detection_for(WOT))
        state.observe(detection_for(WOT, SC))
        state.request("desktop")
        state.observe(detection_for(WOT))
        self.assertEqual(state.target_profile.name, "world-of-tanks")

    def test_the_override_follows_a_rename(self):
        """Renaming the overriding profile must not fall back to the desktop."""
        state = self._state()
        state.request("world-of-tanks")
        state.rename_profile("world-of-tanks", "wot")
        self.assertEqual(state.manual_override, "wot")
        self.assertEqual(state.target_profile.name, "wot")

    def test_deleting_the_overriding_profile_ends_the_override(self):
        state = self._state()
        state.request("star-citizen")
        state.delete_profile("star-citizen")
        self.assertIsNone(state.manual_override)


class GameChangeTests(unittest.TestCase):
    """What observe reports, so the daemon can announce it."""

    def _state(self):
        return DaemonState(config=make_config(DESKTOP, WOT, SC))

    def test_a_game_starting_is_reported(self):
        change = self._state().observe(detection_for(WOT))
        self.assertEqual(change.started, "world-of-tanks")
        self.assertIsNone(change.stopped)

    def test_a_game_stopping_is_reported(self):
        state = self._state()
        state.observe(detection_for(WOT))
        change = state.observe(detection_for())
        self.assertIsNone(change.started)
        self.assertEqual(change.stopped, "world-of-tanks")

    def test_a_second_game_starting_is_a_change(self):
        state = self._state()
        state.observe(detection_for(WOT))
        change = state.observe(detection_for(WOT, SC))
        self.assertEqual(change.started, "star-citizen")
        self.assertEqual(change.stopped, "world-of-tanks")

    def test_no_change_reports_nothing(self):
        state = self._state()
        state.observe(detection_for(WOT))
        self.assertIsNone(state.observe(detection_for(WOT)))

    def test_a_request_is_not_a_game_change(self):
        state = self._state()
        state.request("world-of-tanks")
        self.assertIsNone(state.observe(detection_for()))


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


class RefusedLoadTests(unittest.TestCase):
    """A refused load is not retried until something changes (#8).

    It used to be retried every check, logging an error and possibly
    rewriting the mouse's flash each time.
    """

    def _refused(self):
        state = DaemonState(config=make_config(DESKTOP, WOT))
        state.mark_refused()
        return state

    def test_a_refused_target_does_not_need_a_write(self):
        self.assertFalse(self._refused().needs_write)

    def test_drift_does_not_retry_a_refused_load(self):
        state = self._refused()
        state.observe_active_slot(1)
        self.assertFalse(state.needs_write)

    def test_a_config_change_retries(self):
        from dataclasses import replace

        state = self._refused()
        state.config = replace(state.config, poll_interval=3.0)
        self.assertTrue(state.needs_write)

    def test_a_different_target_is_not_refused(self):
        state = self._refused()
        state.request("world-of-tanks")
        self.assertTrue(state.needs_write)

    def test_the_refused_target_coming_back_is_retried_after_another_loads(self):
        state = self._refused()
        state.request("world-of-tanks")
        state.mark_loaded("world-of-tanks")
        state.request("desktop")
        self.assertTrue(state.needs_write, "a successful load ends the refusal")

    def test_clearing_retries(self):
        """A reconnect clears it: the new connection may accept the load."""
        state = self._refused()
        state.clear_refusal()
        self.assertTrue(state.needs_write)

    def test_the_refusal_is_reported(self):
        self.assertEqual(self._refused().refused_profile, "desktop")
        self.assertIsNone(DaemonState(config=make_config(DESKTOP, WOT)).refused_profile)


class SeededProfileTests(unittest.TestCase):
    """A new profile starts as a copy of the desktop profile's device settings.

    An empty profile writes nothing to the mouse, so loading one only changed
    which slot was active — which reads as broken in the UI.
    """

    def _state(self):
        desktop = Profile(
            name="desktop",
            report_rate=1000,
            resolutions=({"dpi": 800, "default": True},),
            bindings={0: Binding("button", 1), 7: Binding("special", "resolution-up")},
            leds=({"index": 0, "mode": "cycle", "duration": 8000},),
        )
        return DaemonState(config=make_config(desktop, WOT))

    def test_a_new_profile_copies_the_desktop_bindings(self):
        state = self._state()
        state.create_profile("new-game")
        profile = state.config.profile_named("new-game")
        self.assertEqual(profile.bindings[7].value, "resolution-up")

    def test_a_new_profile_copies_the_desktop_device_settings(self):
        state = self._state()
        state.create_profile("new-game")
        profile = state.config.profile_named("new-game")
        self.assertEqual(profile.report_rate, 1000)
        self.assertEqual(profile.resolutions, ({"dpi": 800, "default": True},))
        self.assertEqual(profile.leds[0]["mode"], "cycle")

    def test_the_copy_is_independent_of_the_desktop_profile(self):
        state = self._state()
        state.create_profile("new-game")
        state.set_binding("new-game", 0, Binding("key", "KEY_F"))
        self.assertEqual(state.config.desktop.bindings[0].value, 1)

    def test_the_new_profile_keeps_its_own_name_and_games(self):
        state = self._state()
        state.create_profile("new-game", executable="NewGame.exe")
        profile = state.config.profile_named("new-game")
        self.assertEqual(profile.name, "new-game")
        self.assertEqual(profile.games[0].executable, "NewGame.exe")
