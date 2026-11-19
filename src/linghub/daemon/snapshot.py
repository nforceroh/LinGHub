"""A read-only view of daemon state for the D-Bus interface.

Keeping this separate from DaemonState means the interface cannot mutate the
daemon's internals, and it can be constructed in tests without a daemon.

`read_view` is the one read a client makes: the daemon's state plus one
profile's editable sections. It is a pure function of DaemonState, so the two
halves cannot disagree, and the adapter only turns the result into D-Bus types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .state import DaemonState


@dataclass(frozen=True)
class StateSnapshot:
    profile_names: tuple[str, ...] = ()
    loaded_profile: str | None = None
    detected_game: str | None = None
    desktop_profile: str = "desktop"


@dataclass(frozen=True)
class ProfileSnapshot:
    """One profile's editable sections; empty for an unknown profile."""

    # (index, type, value), in button order.
    bindings: tuple[tuple[int, str, object], ...] = ()
    # Each zone's settings, including its index, in zone order.
    leds: tuple[dict, ...] = ()
    # (dpi, is_default, is_disabled), in slot order.
    resolutions: tuple[tuple[int, bool, bool], ...] = ()
    # The rates the device accepts, in Hz.
    report_rates: tuple[int, ...] = ()
    # The profile's report rate in Hz, or 0 if unset.
    report_rate: int = 0


@dataclass(frozen=True)
class View:
    state: StateSnapshot
    profile: ProfileSnapshot = field(default_factory=ProfileSnapshot)


def read_view(
    state: DaemonState, profile: str, report_rates: tuple[int, ...]
) -> View:
    """The daemon's state, and the named profile's sections.

    An unknown profile yields empty sections rather than an error: a client
    may ask about a profile that has just been deleted, and "nothing there"
    is the answer it wants. The device's report rates are reported either
    way, since they belong to the mouse rather than the profile.
    """
    snapshot = StateSnapshot(
        profile_names=tuple(p.name for p in state.config.profiles),
        loaded_profile=state.loaded_profile,
        detected_game=state.current_game,
        desktop_profile=state.config.desktop_profile,
    )
    found = state.config.profile_named(profile)
    if found is None:
        return View(snapshot, ProfileSnapshot(report_rates=tuple(report_rates)))
    return View(snapshot, ProfileSnapshot(
        bindings=tuple(
            (index, binding.type, binding.value)
            for index, binding in sorted(found.bindings.items())
        ),
        leds=tuple(
            dict(entry) for entry in sorted(found.leds, key=lambda e: int(e["index"]))
        ),
        resolutions=tuple(
            (int(slot.get("dpi", 0)), bool(slot.get("default")), bool(slot.get("disabled")))
            for slot in found.resolutions
        ),
        report_rates=tuple(report_rates),
        report_rate=int(found.report_rate or 0),
    ))
