"""The assignment catalogue: everything a button can be assigned, as data.

Two interfaces used to describe the same vocabulary. The sidebar built its
grouped, searchable rows from the label tables directly; the binding editor
kept its own mode table with its own choice lists. They drifted: the sidebar
offered the full curated keyboard, the editor's dropdown only the common
keys, so the same profile could hold a binding the dialog could not show.

This module owns the vocabulary once. The sidebar reads the groups; the
editor reads the modes. Adding a key, a command or a special action is one
entry here, and it appears everywhere — drag, click and dialog.

Every value must be one the hardware path can encode: `hardware.mapping.encode`
is the authority, and the tests hold this catalogue to it.
"""

from __future__ import annotations

from dataclasses import dataclass

from .binding_labels import (
    BUTTON_CHOICES,
    COMMON_KEYS,
    COMMAND_CHORDS,
    SPECIAL_CHOICES,
    _all_keys,
    describe_chord,
)


# --- the sidebar's view: choices grouped the way the reference groups them ---

GROUPS: tuple[str, ...] = ("Commands", "Keys", "Macros", "System")


@dataclass(frozen=True)
class AssignmentChoice:
    kind: str
    value: object
    label: str
    group: str


def assignment_choices() -> tuple[AssignmentChoice, ...]:
    """Every assignment choice, grouped like the reference.

    Commands are key combinations applications respond to, encoded as
    modifier chords. Keys are single keys. Macros are single keys sent the
    macro way, which some games need. System covers mouse actions and
    functions. Nothing is the explicit no-assignment.
    """
    choices = []
    for keys, label in COMMAND_CHORDS:
        choices.append(
            AssignmentChoice("macro", describe_chord(list(keys)), label, "Commands")
        )
    # The full keyboard: every key the kernel defines, after the common
    # shortcuts. Duplicates are dropped so a common key is not listed twice.
    seen = {value for value, _label in COMMON_KEYS}
    for value, label in COMMON_KEYS:
        choices.append(AssignmentChoice("key", value, label, "Keys"))
    for value, label in _all_keys():
        if value not in seen:
            seen.add(value)
            choices.append(AssignmentChoice("key", value, label, "Keys"))
    for value, label in COMMON_KEYS:
        choices.append(
            AssignmentChoice("macro", value, f"{label} (macro)", "Macros")
        )
    for value, label in SPECIAL_CHOICES:
        choices.append(AssignmentChoice("special", value, label, "System"))
    for value, label in BUTTON_CHOICES:
        choices.append(AssignmentChoice("button", value, label, "System"))
    choices.append(AssignmentChoice("disabled", None, "Nothing", "System"))
    # Alphabetical within each group, so an option can be found by scanning
    # instead of remembering the order the tables happen to be written in.
    return tuple(sorted(choices, key=lambda choice: (choice.group, choice.label.casefold())))


def filter_assignment_choices(
    choices: tuple[AssignmentChoice, ...], query: str
) -> tuple[AssignmentChoice, ...]:
    """Case-insensitive label/group search."""
    needle = query.strip().casefold()
    if not needle:
        return choices
    return tuple(
        choice
        for choice in choices
        if needle in choice.label.casefold()
        or needle in choice.group.casefold()
    )


def choices_in_group(
    choices: tuple[AssignmentChoice, ...], group: str
) -> tuple[AssignmentChoice, ...]:
    """The choices belonging to one group."""
    return tuple(choice for choice in choices if choice.group == group)


# --- the editor's view: one mode per way of expressing a binding -------------

# Mode names, so callers can compare without string literals.
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
        assert self.choices is not None, f"{mode_name(self)} has no choices"
        return self.choices


def mode_name(mode: Mode) -> str:
    return mode.name


def _keys_choices() -> tuple[tuple[str, str], ...]:
    """The full curated keyboard, shared by the key and macro modes.

    The sidebar's Keys group offers every basic-keyboard key; the editor's
    dropdown offers the same list, so a binding staged from the sidebar is
    always visible and re-selectable in the dialog.
    """
    return tuple(_all_keys())


MODES: tuple[Mode, ...] = (
    Mode(MODE_KEY, "A single key", "key", DROPDOWN, _keys_choices()),
    Mode(
        MODE_KEY_MACRO, "A single key, as a macro", "macro",
        DROPDOWN, _keys_choices(),
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
