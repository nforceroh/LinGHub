"""What one tick decides, separated from what it does.

The daemon's tick used to be one async body that detected a game, updated the
state, decided the fate of a manual override, emitted signals, read the
hardware and wrote a profile. The decision in the middle — when a manual
choice lives and dies — is the part with the bug history: an override that
never cleared left a gaming profile on the mouse with no game running.

That decision is pure. It depends on three facts and produces two answers, so
it lives here where it can be tested without a bus, a device, an event loop,
or a patched module global.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TickDecision:
    """What the tick should do, given what it just saw."""

    # The manual override to carry into the next tick, or None if it is spent.
    override: str | None
    # The game that started, if one did.
    detected: str | None = None
    # The game that stopped, if one did.
    exited: str | None = None


def decide(
    previous_game: str | None,
    detected_game: str | None,
    override: str | None,
) -> TickDecision:
    """Decide the override's fate and which game events to announce.

    Two rules, both learned from bugs:

    A manual choice lasts until the detected game changes. Picking a profile
    while a game runs must not be undone by the next tick, but a game starting
    or stopping is a new situation and detection takes over again.

    A manual choice with no game running has nothing to override. Without this
    the override stuck forever, leaving a gaming profile on the mouse with no
    game — the desktop profile is what should be loaded.
    """
    detected = None
    exited = None
    if detected_game != previous_game:
        override = None
        if detected_game is not None:
            detected = detected_game
        elif previous_game is not None:
            exited = previous_game

    if override is not None and detected_game is None:
        override = None

    return TickDecision(override=override, detected=detected, exited=exited)
