"""The one place that knows the D-Bus member names and signatures.

Both sides of the bus need the same facts: the daemon declares a method's
signature in its annotations, and the client has to send a matching signature
string. Nothing used to check the two against each other, so a typo was a
runtime error rather than a build error - and three were wrong during this
project's own work.

The annotations cannot read from a table (dbus-fast introspects the
`@method` decorator), so this module declares the truth and a test compares
the two. That way the daemon remains the authority and the client cannot drift
from it silently.
"""

from __future__ import annotations

from dataclasses import dataclass


SERVICE = "org.linghub.Manager"
PATH = "/org/linghub/Manager"
INTERFACE = "org.linghub.Manager"


@dataclass(frozen=True)
class Member:
    """One D-Bus method: its name, its input signature, and its output."""

    name: str
    input: str = ""
    output: str = ""

    def call_body(self, *args) -> list:
        """Positional arguments, checked against the declared signature."""
        expected = _arity(self.input)
        if len(args) != expected:
            raise TypeError(
                f"{self.name} takes {expected} argument(s) for {self.input!r}, "
                f"got {len(args)}"
            )
        return list(args)


def _arity(signature: str) -> int:
    """How many top-level arguments a signature describes."""
    from dbus_fast.signature import SignatureTree

    return len(SignatureTree(signature).types)


# Methods. Keep in step with ManagerInterface; a test enforces it.
LOAD_PROFILE = Member("LoadProfile", "s", "b")
RELOAD = Member("Reload", "", "b")
LIST_PROFILES = Member("ListProfiles", "", "as")
GET_VIEW = Member(
    "GetView", "s",
    # state, profile sections, then every profile's canvas summary:
    # (name, default DPI, report rate, and its games as (executable, name)).
    "(sssasa(iss)a(us(uuu)uu)a(uuuu)auu)a(ssu(ss)s)",
)
SET_BINDING = Member("SetBinding", "siss", "b")
CLEAR_BINDING = Member("ClearBinding", "si", "b")
SET_LEDS = Member("SetLeds", "ssuuuuu", "b")
SET_RESOLUTION = Member("SetResolution", "siubb", "b")
SET_REPORT_RATE = Member("SetReportRate", "su", "b")
CREATE_PROFILE = Member("CreateProfile", "ss", "b")
RENAME_PROFILE = Member("RenameProfile", "ss", "b")
DELETE_PROFILE = Member("DeleteProfile", "s", "b")
DUPLICATE_PROFILE = Member("DuplicateProfile", "ss", "b")
RENAME_GAME = Member("RenameGame", "sss", "b")

METHODS: tuple[Member, ...] = (
    LOAD_PROFILE, RELOAD, LIST_PROFILES, GET_VIEW,
    SET_BINDING, CLEAR_BINDING,
    SET_LEDS,
    SET_RESOLUTION,
    SET_REPORT_RATE,
    CREATE_PROFILE, RENAME_PROFILE, DELETE_PROFILE,
    DUPLICATE_PROFILE, RENAME_GAME,
)

BY_NAME = {member.name: member for member in METHODS}


@dataclass(frozen=True)
class Property:
    """One read-only D-Bus property: its name and its signature."""

    name: str
    signature: str


# The daemon's app version. A property rather than a GetView field, so a
# daemon too old to have it answers "unknown property" and nothing else
# breaks (ADR-0009).
VERSION = Property("Version", "s")
