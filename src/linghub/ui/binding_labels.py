"""What a stored binding is called, in one line.

The vocabulary itself — which keys, specials, buttons and chords are on
offer — lives in assignment_catalogue, the module that offers it. This module
describes what the config holds: the describe functions read the catalogue's
label tables and answer with the name a person would say.

The UI cannot invent binding values: every option in the catalogue has to be
one the hardware path can actually encode, or the user picks something that
fails at commit time with a cryptic error. `hardware.mapping.encode` is the
authority on whether it works.
"""

from __future__ import annotations

from .assignment_catalogue import (
    _MODIFIER_NAMES,
    BUTTON_LABELS,
    KEY_LABELS,
    SPECIAL_LABELS,
)


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
