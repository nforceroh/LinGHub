"""Which slot a profile belongs in, and whether the mouse agrees.

The G502 has five slots, but only 0 and 1 can be activated: slots 2-4 are
disabled in the hardware, so ratbagd refuses to make them active. Per-game
profiles are therefore kept on disk and loaded into slot 1 when their game
starts, rather than each being pinned to a slot of its own. See ADR-0001.

That rule used to live inside `DaemonState`, next to the code that edits
profiles' bindings and DPI tables — two unrelated questions sharing a class.
Keeping the Slot rules here means the config side can be read without knowing
anything about slots, and ADR-0001 can be read as code.
"""

from __future__ import annotations

from ..domain.profile import Profile


DESKTOP_SLOT = 0
GAMING_SLOT = 1


def slot_for(profile: Profile) -> int:
    """The slot a profile belongs in: 0 for desktop, 1 for a gaming profile."""
    return DESKTOP_SLOT if profile.is_desktop else GAMING_SLOT


def drifted(loaded: Profile | None, active_slot: int | None) -> bool:
    """True when the hardware is not where the loaded profile belongs.

    Something outside the daemon can move the active slot: the mouse's own
    profile button, a `ratbagctl` call, or a KVM reconnect that makes ratbagd
    fall back to slot 0. Noticing the disagreement is what lets the next write
    correct it.

    A missing loaded profile is not drift. Before the first write there is
    nothing to disagree with, and treating "unknown" as drift would make the
    daemon rewrite on every tick.
    """
    if loaded is None:
        return False
    return active_slot != slot_for(loaded)