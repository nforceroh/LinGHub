"""Tests for the UI's non-graphical logic.

The diagram and window need a display, so these cover the parts that do not:
the button map and the daemon client's message handling.
"""

import unittest
from types import SimpleNamespace

from dbus_fast import MessageType

from linghub.ui.buttonmap import (
    BUTTONS,
    BY_INDEX,
    MANUAL,
    describe,
    manual_number,
)
from linghub.ui.client import INTERFACE, DaemonClient


class ButtonMapTests(unittest.TestCase):
    def test_covers_every_ratbag_index(self):
        self.assertEqual(sorted(BY_INDEX), list(range(11)))

    def test_manual_numbers_are_one_to_eleven(self):
        self.assertEqual(sorted(MANUAL.values()), list(range(1, 12)))

    def test_manual_numbers_match_the_documented_map(self):
        """docs/button-map.md is the source of truth for this mapping.

        ratbag and the manual disagree on the tilt wheel and the profile
        button, which is exactly the sort of thing that silently rots.
        """
        self.assertEqual(MANUAL[10], 9)  # scroll left
        self.assertEqual(MANUAL[9], 10)  # scroll right
        self.assertEqual(MANUAL[8], 11)  # profile select
        self.assertEqual(MANUAL[0], 1)  # left click
        self.assertEqual(MANUAL[7], 8)  # last of the aligned run

    def test_manual_number_of_unknown_index(self):
        self.assertEqual(manual_number(99), "-")

    def test_positions_are_fractions(self):
        for spot in BUTTONS:
            self.assertGreaterEqual(spot.x, 0.0)
            self.assertLessEqual(spot.x, 1.0)
            self.assertGreaterEqual(spot.y, 0.0)
            self.assertLessEqual(spot.y, 1.0)

    def test_positions_are_distinct(self):
        """Two hotspots on the same spot would make one unclickable."""
        seen = set()
        for spot in BUTTONS:
            key = (round(spot.x, 3), round(spot.y, 3))
            self.assertNotIn(key, seen, f"duplicate position for button {spot.index}")
            seen.add(key)

    def test_describe_includes_g_name(self):
        self.assertEqual(describe(3), "Back (G4)")

    def test_describe_omits_empty_g_name(self):
        self.assertEqual(describe(0), "Left click")

    def test_describe_handles_unknown_index(self):
        self.assertEqual(describe(99), "Button 99")


class GetViewDecodeTests(unittest.TestCase):
    """The D-Bus struct decodes to the view the window's panels consume.

    GetView carries the most complex signature in the contract, so the
    round trip is pinned here: raw struct in, DaemonView out, every shape
    the panels expect present.
    """

    def _raw(self):
        return (
            (
                "wot", "x.exe", "desktop", ["desktop", "wot"],
                [(0, "key", "KEY_F"), (3, "button", "4")],
                [(0, "breathing", (255, 0, 0), 128, 3000)],
                [(0, 800, 1, 0), (1, 1600, 0, 1)],
                [125, 250, 500, 1000],
                500,
            ),
            [("wot", 1600, 500, [("x.exe", "World of Tanks")])],
        )

    def test_the_struct_decodes_to_the_view(self):
        import asyncio

        from linghub.daemon_view import ProfileSummary
        from linghub.ui.client import DaemonClient, DaemonView

        client = DaemonClient()

        async def fake_invoke(member, *args):
            self.assertIs(member, __import__(
                "linghub.dbus_contract", fromlist=["GET_VIEW"]
            ).GET_VIEW)
            self.assertEqual(args, ("wot",))
            return self._raw()

        client._invoke = fake_invoke
        view = asyncio.run(client.get_view("wot"))

        self.assertIsInstance(view, DaemonView)
        self.assertEqual(view.state.active_profile, "wot")
        self.assertEqual(view.state.detected_game, "x.exe")
        self.assertEqual(view.state.desktop_profile, "desktop")
        self.assertEqual(view.state.profiles, ("desktop", "wot"))
        self.assertEqual(
            view.profile.bindings,
            {0: ("key", "KEY_F"), 3: ("button", "4")},
        )
        self.assertEqual(
            view.profile.leds,
            {0: {"mode": "breathing", "color": (255, 0, 0),
                 "brightness": 128, "duration": 3000}},
        )
        self.assertEqual(
            view.profile.resolutions,
            [
                {"index": 0, "dpi": 800, "default": True, "disabled": False},
                {"index": 1, "dpi": 1600, "default": False, "disabled": True},
            ],
        )
        self.assertEqual(view.profile.report_rates, (125, 250, 500, 1000))
        self.assertEqual(view.profile.report_rate, 500)
        self.assertEqual(
            view.summaries,
            (ProfileSummary(name="wot", dpi=1600, report_rate=500,
                            games=(("x.exe", "World of Tanks"),)),),
        )

    def test_empty_sections_decode_to_empty_collections(self):
        """An unknown profile yields empty sections, not an error."""
        import asyncio

        from linghub.ui.client import DaemonClient

        client = DaemonClient()

        async def fake_invoke(_member, *args):
            return (("", "", "desktop", [], [], [], [], [], 0), [])

        client._invoke = fake_invoke
        view = asyncio.run(client.get_view("gone"))
        self.assertEqual(view.profile.bindings, {})
        self.assertEqual(view.profile.leds, {})
        self.assertEqual(view.profile.resolutions, [])
        self.assertEqual(view.profile.report_rates, ())
        self.assertEqual(view.profile.report_rate, 0)


class SignalHandlingTests(unittest.TestCase):
    def setUp(self):
        self.calls = 0
        self.client = DaemonClient()
        self.client.set_change_handler(self._bump)

    def _bump(self):
        self.calls += 1

    def _signal(self, interface=INTERFACE, member="ProfileChanged"):
        return SimpleNamespace(
            message_type=MessageType.SIGNAL, interface=interface, member=member, body=["x"]
        )

    def test_our_signal_triggers_change(self):
        self.client._handle_signal(self._signal())
        self.assertEqual(self.calls, 1)

    def test_other_interface_is_ignored(self):
        self.client._handle_signal(self._signal(interface="org.example.Other"))
        self.assertEqual(self.calls, 0)

    def test_method_return_is_ignored(self):
        message = SimpleNamespace(
            message_type=MessageType.METHOD_RETURN, interface=INTERFACE,
            member="ProfileChanged", body=["x"],
        )
        self.client._handle_signal(message)
        self.assertEqual(self.calls, 0)

    def test_no_handler_is_safe(self):
        client = DaemonClient()
        client._handle_signal(self._signal())  # must not raise

    def _owner_changed(self, name):
        return SimpleNamespace(
            message_type=MessageType.SIGNAL, interface="org.freedesktop.DBus",
            member="NameOwnerChanged", body=[name, "", ":1.42"],
        )

    def test_the_daemon_starting_or_stopping_triggers_change(self):
        """With no poll, this is how a client notices the daemon came or went."""
        from linghub.dbus_contract import SERVICE

        self.client._handle_signal(self._owner_changed(SERVICE))
        self.assertEqual(self.calls, 1)

    def test_another_name_changing_owner_is_ignored(self):
        self.client._handle_signal(self._owner_changed("org.example.Other"))
        self.assertEqual(self.calls, 0)



class DaemonVersionTests(unittest.TestCase):
    """Reading the daemon's version, which is a property of its own (ADR-0009)."""

    def _client_answering(self, reply):
        client = DaemonClient()
        sent = []

        class Bus:
            async def call(self, message):
                sent.append(message)
                return reply

        client._bus = Bus()
        return client, sent

    def _error(self, name):
        return SimpleNamespace(
            message_type=MessageType.ERROR, error_name=name, body=["no"],
        )

    def test_reads_the_version_property(self):
        import asyncio
        from dbus_fast import Variant

        from linghub import version

        client, sent = self._client_answering(SimpleNamespace(
            message_type=MessageType.METHOD_RETURN, body=[Variant("s", "0.1.0+3.g5c27eef")],
        ))
        self.assertEqual(
            asyncio.run(client.daemon_version()),
            version.DaemonVersion.known("0.1.0+3.g5c27eef"),
        )
        self.assertEqual(sent[0].member, "Get")
        self.assertEqual(sent[0].body, [INTERFACE, "Version"])

    def test_a_daemon_without_the_property_predates_reporting(self):
        import asyncio
        from linghub import version

        for name in ("org.freedesktop.DBus.Error.UnknownProperty",
                     "org.freedesktop.DBus.Error.InvalidArgs"):
            with self.subTest(error=name):
                client, _ = self._client_answering(self._error(name))
                self.assertEqual(
                    asyncio.run(client.daemon_version()),
                    version.DaemonVersion.predates_reporting(),
                )

    def test_no_daemon_is_not_running_not_old(self):
        import asyncio
        from linghub import version

        client, _ = self._client_answering(
            self._error("org.freedesktop.DBus.Error.ServiceUnknown")
        )
        self.assertEqual(
            asyncio.run(client.daemon_version()), version.DaemonVersion.not_running()
        )

    def test_any_other_error_is_unreadable_not_not_running(self):
        """The bug: a running daemon whose version read failed said "not running"."""
        import asyncio
        from linghub import version

        client, _ = self._client_answering(
            self._error("org.freedesktop.DBus.Error.Failed")
        )
        self.assertEqual(
            asyncio.run(client.daemon_version()), version.DaemonVersion.unreadable()
        )

    def test_a_timeout_is_unreadable(self):
        import asyncio
        from linghub import version

        class Bus:
            async def call(self, _message):
                raise TimeoutError("no answer")

        client = DaemonClient()
        client._bus = Bus()
        self.assertEqual(
            asyncio.run(client.daemon_version()), version.DaemonVersion.unreadable()
        )

    def test_no_connection_is_not_running(self):
        import asyncio
        from linghub import version

        self.assertEqual(
            asyncio.run(DaemonClient().daemon_version()),
            version.DaemonVersion.not_running(),
        )


if __name__ == "__main__":
    unittest.main()
