"""The write order for pending edits: one module, one sequence.

The window used to own this sequence inline, so its tests needed a
half-constructed window and a fake client to check the order. These tests
cross the module's interface directly: pending edits in, client calls out, in
the order the panels present their sections.
"""

import unittest

from linghub.ui.edit_apply import apply
from linghub.ui.pending_edits import PendingEdits


class RecordingClient:
    """Accepts everything, and records the calls in order."""

    def __init__(self, refuse: str | None = None):
        self.calls: list[tuple] = []
        self._refuse = refuse

    async def set_binding(self, profile, index, kind, value):
        self.calls.append(("binding", index, kind, value))
        return self._refuse != "binding"

    async def clear_binding(self, profile, index):
        self.calls.append(("clear", index))
        return self._refuse != "binding"

    async def set_resolution(self, profile, index, dpi, **kw):
        self.calls.append(("resolution", index, dpi))
        return self._refuse != "resolution"

    async def set_report_rate(self, profile, rate):
        self.calls.append(("rate", rate))
        return self._refuse != "rate"

    async def set_leds(self, profile, mode, brightness, duration, color):
        self.calls.append(("leds", mode))
        return self._refuse != "leds"


def full_edits() -> PendingEdits:
    edits = PendingEdits(profile="wot")
    edits.set_binding(2, "key", "KEY_X")
    edits.set_resolutions([(800, True, False)], 1000)
    edits.set_leds("breathing", 255, 8000, (1, 2, 3))
    return edits


class ApplyTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_section_is_written_in_panel_order(self):
        client = RecordingClient()
        rejected = await apply(full_edits(), client)
        self.assertIsNone(rejected)
        self.assertEqual(
            [call[0] for call in client.calls],
            ["binding", "resolution", "rate", "leds"],
        )

    async def test_a_disabled_binding_is_cleared_not_set(self):
        edits = PendingEdits(profile="wot")
        edits.set_binding(3, "disabled", None)
        client = RecordingClient()
        await apply(edits, client)
        self.assertEqual(client.calls, [("clear", 3)])

    async def test_a_refusal_stops_the_sequence_and_names_the_section(self):
        client = RecordingClient(refuse="resolution")
        rejected = await apply(full_edits(), client)
        self.assertEqual(rejected, "The daemon rejected DPI preset 1.")
        kinds = [call[0] for call in client.calls]
        self.assertNotIn("rate", kinds)
        self.assertNotIn("leds", kinds)

    async def test_an_untouched_section_is_never_written(self):
        edits = PendingEdits(profile="wot")
        edits.set_binding(2, "key", "KEY_X")
        client = RecordingClient()
        await apply(edits, client)
        self.assertEqual([call[0] for call in client.calls], ["binding"])


if __name__ == "__main__":
    unittest.main()
