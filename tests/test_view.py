"""Tests for the one read a client makes: the daemon's state and a profile.

`read_view` is a pure function of the daemon's state, so these run against a
real DaemonState with no bus, no adapter and no fake collaborators.
"""

import unittest

from linghub.config import Config
from linghub.daemon.snapshot import read_view
from linghub.daemon.state import DaemonState
from linghub.domain.profile import Binding, Game, Profile

RATES = (125, 250, 500, 1000)


def make_state() -> DaemonState:
    return DaemonState(config=Config(
        profiles=[
            Profile(name="desktop"),
            Profile(
                name="wot", games=(Game("x.exe"),),
                bindings={3: Binding("button", 4), 0: Binding("key", "KEY_A")},
                resolutions=({"dpi": 800, "default": True}, {"dpi": 1600, "disabled": True}),
                leds=({"index": 1, "mode": "off"}, {"index": 0, "mode": "on"}),
                report_rate=500,
            ),
        ],
        desktop_profile="desktop",
        poll_interval=2.0,
    ))


class StateTests(unittest.TestCase):
    def test_the_state_reports_what_is_loaded_and_what_exists(self):
        state = make_state()
        state.request("wot")
        state.mark_loaded("wot")
        view = read_view(state, "", RATES)
        self.assertEqual(view.state.loaded_profile, "wot")
        self.assertEqual(view.state.desktop_profile, "desktop")
        self.assertEqual(view.state.profile_names, ("desktop", "wot"))
        self.assertIsNone(view.state.detected_game)

    def test_the_detected_game_is_the_current_game(self):
        from linghub.discovery.detector import Detection, Match
        from linghub.discovery.processes import ProcessInfo

        state = make_state()
        wot = state.config.profile_named("wot")
        state.observe(Detection(matches=[Match(
            game=wot.games[0], profile=wot,
            process=ProcessInfo(pid=1, name="p", executable_path="x.exe",
                                real_executable_path="x.exe", command="x.exe"),
        )], rejections=[], considered=1))
        self.assertEqual(read_view(state, "", RATES).state.detected_game, "wot")


class ProfileSectionTests(unittest.TestCase):
    def test_bindings_are_in_button_order(self):
        view = read_view(make_state(), "wot", RATES)
        self.assertEqual(view.profile.bindings, ((0, "key", "KEY_A"), (3, "button", 4)))

    def test_resolutions_are_in_slot_order(self):
        view = read_view(make_state(), "wot", RATES)
        self.assertEqual(view.profile.resolutions, ((800, True, False), (1600, False, True)))

    def test_leds_are_in_zone_order(self):
        view = read_view(make_state(), "wot", RATES)
        self.assertEqual(view.profile.leds, ({"index": 0, "mode": "on"}, {"index": 1, "mode": "off"}))

    def test_the_report_rate_is_the_profiles(self):
        self.assertEqual(read_view(make_state(), "wot", RATES).profile.report_rate, 500)

    def test_an_unset_report_rate_is_zero(self):
        self.assertEqual(read_view(make_state(), "desktop", RATES).profile.report_rate, 0)

    def test_the_accepted_rates_come_from_the_device(self):
        self.assertEqual(read_view(make_state(), "wot", RATES).profile.report_rates, RATES)

    def test_an_unknown_profile_has_empty_sections(self):
        profile = read_view(make_state(), "gone", RATES).profile
        self.assertEqual(
            (profile.bindings, profile.leds, profile.resolutions, profile.report_rate),
            ((), (), (), 0),
        )
        self.assertEqual(profile.report_rates, RATES, "the device's rates do not depend on the profile")


if __name__ == "__main__":
    unittest.main()
