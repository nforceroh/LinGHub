"""What the daemon publishes, and the one failure both sides of the seam raise.

These types are the vocabulary of the daemon/client seam, so they live beside
`dbus_contract` rather than inside `ui/`. The tray is GTK3 and the window is
GTK4, and PyGObject refuses to load two versions of the Gtk namespace in one
process, so the tray must never import anything that reaches GTK4. Keeping
these types here means the tray's import chain never enters `ui/` at all,
instead of relying on `ui/client.py` happening to import no GTK.

This module is a leaf: it imports `dataclasses` and nothing else. That is what
makes the guarantee structural, and `tests/test_daemon_view.py` checks it.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class DaemonUnavailable(RuntimeError):
    """The daemon is not running, or is not answering on the session bus.

    Raised by the client when the bus says nothing owns the daemon's name, and
    by `daemon_access` when the session bus itself cannot be reached. Both mean
    the same thing to a caller: there is no daemon to talk to.
    """


@dataclass(frozen=True)
class ViewState:
    """The state section of a view: what the tray and the title bar show."""

    active_profile: str = ""
    detected_game: str = ""
    desktop_profile: str = "desktop"
    profiles: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProfileView:
    """One profile's editable sections, as the window's panels consume them."""

    bindings: dict[int, tuple[str, str]] = field(default_factory=dict)
    leds: dict[int, dict] = field(default_factory=dict)
    resolutions: list[dict] = field(default_factory=list)
    report_rates: tuple[int, ...] = ()
    report_rate: int = 0


@dataclass(frozen=True)
class DaemonView:
    """Everything a client shows, from one D-Bus read.

    The state section is what the tray and the title bar show; the profile
    section is what the panels edit. One read means a refresh cannot piece a
    view together from two ticks.
    """

    state: ViewState
    profile: ProfileView
