"""Human-readable descriptions of bindings, and the choices we offer.

The UI cannot invent binding values: every option here has to be one the
hardware path can actually encode, or the user picks something that fails at
commit time with a cryptic error. So the vocabulary lives here, in one table,
and `hardware.mapping.encode` is the authority on whether it works.
"""

from __future__ import annotations


# Common mouse-friendly keys, offered as a starting point. Anything not listed
# can still be typed, because the key is resolved from the kernel headers.
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

SPECIAL_LABELS = dict(SPECIAL_CHOICES)
KEY_LABELS = dict(COMMON_KEYS)
BUTTON_LABELS = dict(BUTTON_CHOICES)


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
        return f"Macro: {value}"
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
