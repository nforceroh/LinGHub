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


# The keys visible on a normal basic keyboard: letters, digits, punctuation,
# function row, navigation cluster, modifiers and the numpad. The kernel's
# full table holds hundreds of vendor, remote-control and auxiliary codes no
# physical keyboard has, so the Keys group is curated rather than parsed.
BASIC_KEYS: tuple[str, ...] = (
    # Letters
    *(f"KEY_{chr(c)}" for c in range(ord("A"), ord("Z") + 1)),
    # Digits row
    *(f"KEY_{n}" for n in range(1, 10)), "KEY_0",
    # Function row
    *(f"KEY_F{n}" for n in range(1, 13)),
    # Punctuation, in keyboard order
    "KEY_GRAVE", "KEY_MINUS", "KEY_EQUAL",
    "KEY_BACKSPACE", "KEY_TAB",
    "KEY_LEFTBRACE", "KEY_RIGHTBRACE", "KEY_BACKSLASH",
    "KEY_SEMICOLON", "KEY_APOSTROPHE",
    "KEY_COMMA", "KEY_DOT", "KEY_SLASH",
    "KEY_CAPSLOCK",
    # Space and enter
    "KEY_SPACE", "KEY_ENTER", "KEY_ESC",
    # Modifiers, both sides
    "KEY_LEFTSHIFT", "KEY_RIGHTSHIFT",
    "KEY_LEFTCTRL", "KEY_RIGHTCTRL",
    "KEY_LEFTALT", "KEY_RIGHTALT",
    "KEY_LEFTMETA", "KEY_RIGHTMETA",
    # Navigation cluster
    "KEY_PRINT", "KEY_SCROLLLOCK", "KEY_PAUSE",
    "KEY_INSERT", "KEY_DELETE",
    "KEY_HOME", "KEY_END",
    "KEY_PAGEUP", "KEY_PAGEDOWN",
    "KEY_UP", "KEY_DOWN", "KEY_LEFT", "KEY_RIGHT",
    # Numpad
    "KEY_NUMLOCK", "KEY_KPSLASH", "KEY_KPASTERISK", "KEY_KPMINUS",
    "KEY_KPPLUS", "KEY_KPENTER", "KEY_KPDOT",
    *(f"KEY_KP{n}" for n in range(1, 10)), "KEY_KP0",
)


# Punctuation keys are shown as the character the key prints, the way the
# keycap itself is labelled, rather than as a word.
_PUNCTUATION_LABELS = {
    "KEY_GRAVE": "`",
    "KEY_MINUS": "-",
    "KEY_EQUAL": "=",
    "KEY_LEFTBRACE": "[",
    "KEY_RIGHTBRACE": "]",
    "KEY_BACKSLASH": "\\",
    "KEY_SEMICOLON": ";",
    "KEY_APOSTROPHE": "'",
    "KEY_COMMA": ",",
    "KEY_DOT": ".",
    "KEY_SLASH": "/",
}


# Numpad keys read the way their keycaps do: "Num 5", "Num +", "Num Enter".
_NUMPAD_LABELS = {
    "KEY_KP0": "Num 0", "KEY_KP1": "Num 1", "KEY_KP2": "Num 2",
    "KEY_KP3": "Num 3", "KEY_KP4": "Num 4", "KEY_KP5": "Num 5",
    "KEY_KP6": "Num 6", "KEY_KP7": "Num 7", "KEY_KP8": "Num 8",
    "KEY_KP9": "Num 9",
    "KEY_KPSLASH": "Num /", "KEY_KPASTERISK": "Num *",
    "KEY_KPMINUS": "Num -", "KEY_KPPLUS": "Num +",
    "KEY_KPENTER": "Num Enter", "KEY_KPDOT": "Num .",
    "KEY_NUMLOCK": "Num Lock",
}


def _all_keys() -> tuple[tuple[str, str], ...]:
    """The basic keyboard's keys with readable labels.

    Punctuation shows the character the key prints ("'", "/", "\"), the way
    the keycap does. Everything else comes from the common table where a
    friendlier name exists ("Grave (console)"), otherwise the code is
    humanized ("KEY_F5" -> "F5").
    """
    return tuple(
        (name, _NUMPAD_LABELS.get(name, _PUNCTUATION_LABELS.get(
            name, KEY_LABELS.get(name, name.replace("KEY_", "").title())
        )))
        for name in BASIC_KEYS
    )


# Common mouse-friendly keys, offered first in the Keys group. The full
# keyboard follows them.
COMMON_KEYS: tuple[tuple[str, str], ...] = (
    ("KEY_F", "F"),
    ("KEY_R", "R"),
    ("KEY_E", "E"),
    ("KEY_Q", "Q"),
    ("KEY_SPACE", "Space"),
    ("KEY_LEFTSHIFT", "Left Shift"),
    ("KEY_LEFTCTRL", "Left Ctrl"),
    ("KEY_LEFTALT", "Left Alt"),
    ("KEY_TAB", "Tab"),
    ("KEY_ESC", "Escape"),
    ("KEY_ENTER", "Enter"),
    ("KEY_1", "1"),
    ("KEY_2", "2"),
    ("KEY_3", "3"),
    ("KEY_4", "4"),
    ("KEY_5", "5"),
    ("KEY_GRAVE", "Grave (console)"),
    ("KEY_M", "M"),
    ("KEY_B", "B"),
    ("KEY_V", "V"),
    ("KEY_C", "C"),
    ("KEY_X", "X"),
    ("KEY_Z", "Z"),
)

# Special actions worth offering. `second-mode` is deliberately absent:
# libratbag rejects it on the G502 (issue #1798).
SPECIAL_CHOICES: tuple[tuple[str, str], ...] = (
    ("resolution-up", "DPI up"),
    ("resolution-down", "DPI down"),
    ("resolution-cycle-up", "Next DPI setting"),
    ("resolution-cycle-down", "Previous DPI setting"),
    ("resolution-alternate", "Momentary DPI shift"),
    ("resolution-default", "Reset DPI to default"),
    ("doubleclick", "Double click"),
    ("wheel-up", "Scroll up"),
    ("wheel-down", "Scroll down"),
    ("wheel-left", "Scroll left"),
    ("wheel-right", "Scroll right"),
    ("profile-cycle-up", "Next profile"),
    ("profile-cycle-down", "Previous profile"),
    ("battery-level", "Battery level"),
)

# Mouse buttons that a physical button can be remapped to emit.
BUTTON_CHOICES: tuple[tuple[int, str], ...] = (
    (1, "Left click"),
    (2, "Middle click"),
    (3, "Right click"),
    (4, "Back"),
    (5, "Forward"),
    (6, "Back (extra)"),
    (7, "Forward (extra)"),
)

# Key combinations applications respond to, offered as ready-made commands.
# Each is encoded as a modifier chord: press modifiers, tap the key, release
# them in reverse. The spec is built by describe_chord, so it always matches
# what the encoder accepts.
COMMAND_CHORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("KEY_LEFTCTRL", "KEY_V"), "Paste"),
    (("KEY_LEFTCTRL", "KEY_C"), "Copy"),
    (("KEY_LEFTCTRL", "KEY_X"), "Cut"),
    (("KEY_LEFTCTRL", "KEY_S"), "Save"),
    (("KEY_LEFTCTRL", "KEY_W"), "Close tab"),
    (("KEY_LEFTCTRL", "KEY_Z"), "Undo"),
    (("KEY_LEFTCTRL", "KEY_Y"), "Redo"),
    (("KEY_LEFTCTRL", "KEY_A"), "Select all"),
    (("KEY_LEFTCTRL", "KEY_N"), "New"),
    (("KEY_LEFTCTRL", "KEY_F"), "Find"),
    (("KEY_LEFTCTRL", "KEY_T"), "New tab"),
    (("KEY_LEFTCTRL", "KEY_P"), "Print"),
    (("KEY_LEFTALT", "KEY_TAB"), "Switch window"),
    (("KEY_LEFTCTRL", "KEY_LEFTSHIFT", "KEY_T"), "Reopen closed tab"),
)

# Short names for the modifier keys, so a chord reads "Ctrl + V" rather than
# "KEY_LEFTCTRL + KEY_V".
_MODIFIER_NAMES = {
    "KEY_LEFTCTRL": "Ctrl",
    "KEY_RIGHTCTRL": "Ctrl",
    "KEY_LEFTALT": "Alt",
    "KEY_RIGHTALT": "Alt",
    "KEY_LEFTSHIFT": "Shift",
    "KEY_RIGHTSHIFT": "Shift",
    "KEY_LEFTMETA": "Super",
    "KEY_RIGHTMETA": "Super",
}

SPECIAL_LABELS = dict(SPECIAL_CHOICES)
KEY_LABELS = dict(COMMON_KEYS)
BUTTON_LABELS = dict(BUTTON_CHOICES)


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
        assert self.choices is not None, f"{self.name} has no choices"
        return self.choices


# The full curated keyboard, shared by the key and macro modes. The sidebar's
# Keys group offers every basic-keyboard key; the editor's dropdown offers the
# same list, so a binding staged from the sidebar is always visible and
# re-selectable in the dialog.
KEYS_CHOICES: tuple[tuple[str, str], ...] = tuple(_all_keys())


MODES: tuple[Mode, ...] = (
    Mode(MODE_KEY, "A single key", "key", DROPDOWN, KEYS_CHOICES),
    Mode(
        MODE_KEY_MACRO, "A single key, as a macro", "macro",
        DROPDOWN, KEYS_CHOICES,
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


def describe_chord(keys: list[str]) -> str:
    """A modifier chord as the macro spec that encodes it."""
    if not keys:
        return ""
    if len(keys) == 1:
        return keys[0]
    *modifiers, key = keys
    presses = " ".join(f"+{m}" for m in modifiers)
    releases = " ".join(f"-{m}" for m in reversed(modifiers))
    return f"{presses} +{key} -{key} {releases}".strip()


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
