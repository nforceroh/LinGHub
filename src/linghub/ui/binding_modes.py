"""The binding editor's modes, as data rather than conditionals.

Six modes were dispatched by four separate chains: kind→mode, mode→initial
value, mode→selected value, mode→stored binding. Adding the sixth mode meant
editing all four, and one was missed - `_select_initial_mode` briefly
referenced an undefined name.

This module holds the mode facts that do not need a widget: which config kind
each mode stores, how to recognise a stored binding as belonging to a mode,
and how the mode's page is built and read. The editor keeps only the GTK
wiring itself: building the named widgets and putting them on the stack.
"""

from __future__ import annotations

from dataclasses import dataclass

from .binding_labels import BUTTON_CHOICES, COMMON_KEYS, SPECIAL_CHOICES


MODE_KEY = "key"
MODE_KEY_MACRO = "key-macro"
MODE_CHORD = "chord"
MODE_SPECIAL = "special"
MODE_BUTTON = "button"
MODE_NOTHING = "nothing"


# How a mode's value is read and written on its page.
DROPDOWN = "dropdown"
CHORD = "chord"
STATIC = "static"


@dataclass(frozen=True)
class Mode:
    """One way of expressing a binding."""

    name: str
    label: str
    # The `type` this mode writes to the config.
    kind: str
    # The kind of page the mode's editor is: a dropdown of choices, the
    # modifier-chord page, or a static label with nothing to edit.
    page: str
    # The choices a dropdown page offers, as (stored value, label) pairs.
    # None for the chord and static pages, which are not dropdowns.
    choices: tuple[tuple[str, str], ...] | None = None

    def dropdown_choices(self) -> tuple[tuple[str, str], ...]:
        """The mode's dropdown choices. Only meaningful for dropdown pages."""
        assert self.choices is not None, f"{self.name} has no choices"
        return self.choices


MODES: tuple[Mode, ...] = (
    Mode(MODE_KEY, "A single key", "key", DROPDOWN, tuple(COMMON_KEYS)),
    Mode(
        MODE_KEY_MACRO, "A single key, as a macro", "macro",
        DROPDOWN, tuple(COMMON_KEYS),
    ),
    Mode(MODE_CHORD, "A modifier chord", "macro", CHORD),
    Mode(MODE_SPECIAL, "A mouse function", "special", DROPDOWN, tuple(SPECIAL_CHOICES)),
    Mode(
        MODE_BUTTON, "Another mouse button", "button",
        DROPDOWN, tuple((str(n), label) for n, label in BUTTON_CHOICES),
    ),
    Mode(MODE_NOTHING, "Nothing", "disabled", STATIC),
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
