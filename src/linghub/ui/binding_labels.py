"""Human-readable descriptions of bindings, and the choices we offer.

The UI cannot invent binding values: every option here has to be one the
hardware path can actually encode, or the user picks something that fails at
commit time with a cryptic error. So the vocabulary lives here, in one table,
and `hardware.mapping.encode` is the authority on whether it works.
"""

from __future__ import annotations


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


def chord_label(keys: tuple[str, ...] | list[str]) -> str:
    """A chord's keys as a readable combination, e.g. "Ctrl + V"."""
    return " + ".join(
        _MODIFIER_NAMES.get(key, KEY_LABELS.get(key, key.replace("KEY_", "")))
        for key in keys
    )


def describe_macro(spec: str) -> str:
    """One line for a macro binding.

    A single-key macro reads as the key; a chord (press modifiers, tap key,
    release in reverse) reads as the combination; anything else falls back to
    the raw spec, which is honest about a sequence we cannot prettify.
    """
    tokens = spec.split()
    if len(tokens) == 1 and not tokens[0].startswith(("+", "-")):
        name = tokens[0]
        return f"Macro: {KEY_LABELS.get(name, name.replace('KEY_', ''))}"
    pressed = [token[1:] for token in tokens if token.startswith("+")]
    released = [token[1:] for token in tokens if token.startswith("-")]
    if pressed and released and list(reversed(pressed)) == released:
        return chord_label(pressed)
    return f"Macro: {spec}"


def describe_binding(kind: str, value: object) -> str:
    """One line describing what a button does."""
    if kind == "disabled" or kind == "":
        return "Nothing"
    if kind == "key":
        name = str(value)
        return KEY_LABELS.get(name, name.replace("KEY_", ""))
    if kind == "special":
        name = str(value)
        return SPECIAL_LABELS.get(name, name)
    if kind == "button":
        try:
            return BUTTON_LABELS.get(int(value), f"Mouse button {value}")
        except (TypeError, ValueError):
            return f"Mouse button {value}"
    if kind == "macro":
        return describe_macro(str(value))
    return f"{kind}: {value}"


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
