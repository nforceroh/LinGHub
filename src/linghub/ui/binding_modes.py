"""The binding editor's modes, as data rather than conditionals.

Six modes were dispatched by four separate chains: kind→mode, mode→initial
value, mode→selected value, mode→stored binding. Adding the sixth mode meant
editing all four, and one was missed - `_select_initial_mode` briefly
referenced an undefined name.

This module holds the mode facts that do not need a widget: which config kind
each mode stores, and how to recognise a stored binding as belonging to a mode.
The editor keeps the widget wiring, which is the part that genuinely needs GTK.
"""

from __future__ import annotations

from dataclasses import dataclass


MODE_KEY = "key"
MODE_KEY_MACRO = "key-macro"
MODE_CHORD = "chord"
MODE_SPECIAL = "special"
MODE_BUTTON = "button"
MODE_NOTHING = "nothing"


@dataclass(frozen=True)
class Mode:
    """One way of expressing a binding."""

    name: str
    label: str
    # The `type` this mode writes to the config.
    kind: str
    # True when the mode's value is a macro spec rather than a plain string.
    is_macro: bool = False


MODES: tuple[Mode, ...] = (
    Mode(MODE_KEY, "A single key", "key"),
    Mode(MODE_KEY_MACRO, "A single key, as a macro", "macro", is_macro=True),
    Mode(MODE_CHORD, "A modifier chord", "macro", is_macro=True),
    Mode(MODE_SPECIAL, "A mouse function", "special"),
    Mode(MODE_BUTTON, "Another mouse button", "button"),
    Mode(MODE_NOTHING, "Nothing", "disabled"),
)

BY_NAME = {mode.name: mode for mode in MODES}
LABELS = tuple((mode.name, mode.label) for mode in MODES)


def is_single_key_macro(spec: object) -> bool:
    """True when a macro spec is one key pressed and released, nothing else."""
    tokens = str(spec).split()
    return len(tokens) == 1 and tokens[0].startswith("KEY_")


def single_key_of(spec: str) -> str:
    return spec.split()[0]


def mode_for(kind: str, value: object = None) -> str:
    """Which mode an existing binding should open in.

    A macro holding exactly one press/release pair is a single key sent the
    macro way, which is what some games need. It gets its own mode so that
    re-saving cannot silently change the mechanism and break the binding.
    """
    if kind == "macro":
        return MODE_KEY_MACRO if is_single_key_macro(value) else MODE_CHORD
    for mode in MODES:
        if mode.kind == kind:
            return mode.name
    return MODE_KEY


def stored_binding(mode: str, value: str) -> tuple[str, object]:
    """The (type, value) pair a mode writes to the config."""
    entry = BY_NAME[mode]
    if entry.kind == "disabled":
        return "disabled", None
    if entry.kind == "button":
        return "button", int(value)
    return entry.kind, value
