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
    from ..domain.profile import Profile


@dataclass(frozen=True)
class StateSnapshot:
    profile_names: tuple[str, ...] = ()
    loaded_profile: str | None = None
    detected_game: str | None = None
    desktop_profile: str = "desktop"


@dataclass(frozen=True)
class ProfileSummary:
    """What the manage-profiles canvas shows for one profile's tile.

    Separate from ProfileSnapshot because the canvas does not open a
    profile's sections: it lists them. Carrying every profile's full sections
    in the state view would make GetView pay for data nobody edits there.
    """

    name: str = ""
    # The default preset's DPI, or 0 when the profile has no default.
    dpi: int = 0
    # The profile's report rate in Hz, or 0 when unset.
    report_rate: int = 0
    # The games the profile carries, as (executable, display name).
    games: tuple[tuple[str, str], ...] = ()


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
    # Every profile's tile data, for the manage-profiles canvas.
    summaries: tuple[ProfileSummary, ...] = ()


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
    summaries = tuple(_summary(p) for p in state.config.profiles)
    found = state.config.profile_named(profile)
    if found is None:
        return View(snapshot, ProfileSnapshot(report_rates=tuple(report_rates)), summaries)
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
    ), summaries)


def _summary(profile: Profile) -> ProfileSummary:
    """The tile data for one profile.

    The DPI shown is the default preset's: it is the value the mouse is at
    while the profile is loaded, and the one a user compares across profiles.
    A profile with no default preset — a hand-edited file can hold one —
    reports 0, which the canvas shows as no DPI line rather than "0 DPI".
    """
    default = next(
        (slot for slot in profile.resolutions if slot.get("default")), None
    )
    return ProfileSummary(
        name=profile.name,
        dpi=int(default.get("dpi", 0)) if default is not None else 0,
        report_rate=int(profile.report_rate or 0),
        games=tuple(
            (game.executable, game.display_name) for game in profile.games
        ),
    )
