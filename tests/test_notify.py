"""Tests for the notification client.

The daemon must keep working on a machine with no notification daemon, so the
important behaviour is that absence is quiet rather than fatal.
"""

import unittest

from linghub.notify import Notifier, profile_message


class ProfileMessageTests(unittest.TestCase):
    def test_game_switch_names_the_game(self):
        summary, body = profile_message("world-of-tanks", "WorldOfTanks.exe")
        self.assertIn("WorldOfTanks.exe", summary)
        self.assertIn("world-of-tanks", body)

    def test_returning_to_desktop_says_so(self):
        summary, body = profile_message("desktop", None)
        self.assertIn("desktop", summary.lower())
        self.assertIn("desktop", body)

    def test_profile_name_is_marked_up(self):
        _summary, body = profile_message("wot", "x.exe")
        self.assertIn("<b>wot</b>", body)

    def test_game_name_is_not_markup(self):
        """A game name comes from a config and could contain anything."""
        summary, _body = profile_message("p", "a<b>&c.exe")
        self.assertIn("a<b>&c.exe", summary)


class UnavailableTests(unittest.TestCase):
    """No notification daemon must be a no-op, not an exception."""

    def test_notify_without_connecting_returns_false(self):
        import asyncio

        self.assertFalse(asyncio.run(Notifier().notify("x", "y")))

    def test_available_is_false_before_connecting(self):
        self.assertFalse(Notifier().available)

    def test_disconnect_without_connecting_is_safe(self):
        Notifier().disconnect()


class FakeReply:
    def __init__(self, body):
        self.body = body


class FakeBus:
    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = 0

    async def call(self, _message):
        self.calls += 1
        return self._replies.pop(0)


class TagTests(unittest.TestCase):
    def _notifier(self, replies):
        notifier = Notifier()
        notifier._bus = FakeBus(replies)
        notifier._available = True
        return notifier

    def test_the_first_notification_does_not_replace_anything(self):
        notifier = self._notifier([FakeReply([7])])
        import asyncio

        asyncio.run(notifier.notify("a", "b", tag="profile"))
        # replaces_id lives in the body we sent; the fake ignores it, so check
        # the stored state instead.
        self.assertEqual(notifier._replaces["profile"], 7)

    def test_a_second_notification_reuses_the_id(self):
        notifier = self._notifier([FakeReply([7]), FakeReply([7])])
        import asyncio

        asyncio.run(notifier.notify("a", "b", tag="profile"))
        asyncio.run(notifier.notify("c", "d", tag="profile"))
        self.assertEqual(notifier._replaces["profile"], 7)

    def test_untagged_notifications_do_not_replace(self):
        notifier = self._notifier([FakeReply([3])])
        import asyncio

        asyncio.run(notifier.notify("a", "b"))
        self.assertEqual(notifier._replaces, {})


if __name__ == "__main__":
    unittest.main()
