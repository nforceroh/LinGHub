"""What can go wrong at the Mouse seam, in the daemon's terms (#8).

The hardware modules fail in many ways: D-Bus errors, ratbagd refusing a
write, a hidraw node vanishing, the encoder rejecting a key name. The daemon
needs to know only what each failure *means*, so the public methods of
`RatbagMouse` and `RatbagConnector` translate every failure into one of
these, once. Anything else that escapes is a bug.

Deliberately not RuntimeError, OSError or ValueError: lower modules raise
those, and a failure must join this family on purpose, never by inheritance.
Before this, what a failure meant depended on its base class and on the order
of the daemon's `except` clauses, and a ValueError from the encoder slipped
through all of them and crash-looped the daemon.
"""

from __future__ import annotations


class MouseFailure(Exception):
    """The base of everything the Mouse seam reports."""


class MouseAbsent(MouseFailure):
    """Connecting found no mouse: not found, or ratbagd not answering.

    Usually transient (a KVM switch, the mouse asleep), so the daemon keeps
    looking. The message says which.
    """


class MouseMisconfigured(MouseFailure):
    """Connecting can't work as things stand: two G502s, an unsupported ratbagd.

    Retrying won't help until something changes, so the message says what
    would fix it. `node` carries the hidraw node a fix would name, when the
    fix is one: a ratbagd that missed a connected mouse can be nudged into
    seeing it (#19), and the daemon hands the node to the retrigger helper.
    """

    def __init__(self, message: str, *, node: str | None = None):
        super().__init__(message)
        self.node = node


class MouseLost(MouseFailure):
    """The connected mouse went away: reconnect."""


class LoadRefused(MouseFailure):
    """The mouse or its driver would not accept a load.

    Not a lost mouse: keep it. The same load is not retried until the
    profile, the config or the connection changes (GLOSSARY: Refused load).
    """


class SlotUnknown(MouseFailure):
    """The mouse could not say which slot it is on, this time.

    Not drift and not a lost mouse: the next check asks again.
    """
