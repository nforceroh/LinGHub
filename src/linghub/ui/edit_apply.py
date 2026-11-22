"""The write order for a profile's pending edits, in one place.

The window used to own this sequence inline: it read the fields off
PendingEdits and called the client once per edit kind, with a rejection
message per kind. That was the only place the order existed, so the tests had
to build a half-constructed window with a fake client to check it, and a new
edit kind meant editing the window.

This module owns the sequence. It takes the pending edits and the client, and
answers with the rejection message or None when the daemon took everything.
The order matters: bindings first, then the DPI table, then the report rate,
then lighting — the same order the panels present them, so a refusal leaves
the user looking at the section that failed.
"""

from __future__ import annotations

from .pending_edits import PendingEdits


async def apply(edits: PendingEdits, client) -> str | None:
    """Write every pending edit; the rejection message, or None on success.

    Stops at the first refusal and says which section refused, so the pending
    edits stay intact and worth retrying — that rule lives in the window's
    settle step, not here.
    """
    for index, edit in sorted(edits.bindings.items()):
        if edit.kind == "disabled":
            ok = await client.clear_binding(edits.profile, index)
        else:
            ok = await client.set_binding(
                edits.profile, index, edit.kind, str(edit.value)
            )
        if not ok:
            return f"The daemon rejected button {index}."

    if edits.resolutions is not None:
        for index, (dpi, is_default, disabled) in enumerate(edits.resolutions):
            if not await client.set_resolution(
                edits.profile, index, dpi,
                make_default=is_default, disabled=disabled,
            ):
                return f"The daemon rejected DPI preset {index + 1}."

    if edits.report_rate is not None:
        if not await client.set_report_rate(edits.profile, edits.report_rate):
            return "The daemon rejected that report rate."

    if edits.leds is not None:
        leds = edits.leds
        if not await client.set_leds(
            edits.profile, leds["mode"], leds["brightness"],
            leds["duration"], leds["color"],
        ):
            return "The daemon rejected that lighting."

    return None
