"""Encoding of bindings into ratbagd's Button.Mapping values.

The mapping is a `(uv)` struct: an action type and a variant payload. The
payload shape depends on the type, so this module owns the translation from
our Binding vocabulary to those numbers.

Special action numbers were verified against a G502 on libratbag 0.18 by
setting each action and reading the resulting mapping back.
"""

from __future__ import annotations

from ..domain.profile import Binding


# Action types, from libratbag-enums.h.
ACTION_NONE = 0
ACTION_BUTTON = 1
ACTION_SPECIAL = 2
ACTION_KEY = 3
ACTION_MACRO = 4

# Special actions are encoded as (1 << 30) + n.
SPECIAL_BASE = 1 << 30

SPECIAL_ACTIONS: dict[str, int] = {
    "doubleclick": 1,
    "wheel-left": 2,
    "wheel-right": 3,
    "wheel-up": 4,
    "wheel-down": 5,
    "ratchet-mode-switch": 6,
    "resolution-cycle-up": 7,
    "resolution-cycle-down": 8,
    "resolution-up": 9,
    "resolution-down": 10,
    "resolution-alternate": 11,
    "resolution-default": 12,
    "profile-cycle-up": 13,
    "profile-cycle-down": 14,
    "profile-up": 15,
    "profile-down": 16,
    "second-mode": 17,
    "battery-level": 18,
}

# Macro event types.
MACRO_KEY_PRESS = 1
MACRO_KEY_RELEASE = 2
MACRO_WAIT = 3


class BindingError(ValueError):
    """A binding cannot be expressed as a ratbagd mapping."""


def _keycode(name: str) -> int:
    """Resolve a Linux input-event-code name to its numeric code.

    Uses the kernel's own table so the mapping cannot drift from the headers.
    """
    import re
    from pathlib import Path

    if not re.fullmatch(r"KEY_[A-Z0-9_]+", name):
        raise BindingError(f"key binding must be a KEY_* name, got {name!r}")

    for header in (
        Path("/usr/include/linux/input-event-codes.h"),
        Path("/usr/include/linux/input.h"),
    ):
        try:
            text = header.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        match = re.search(rf"^#define\s+{name}\s+(0x[0-9a-fA-F]+|\d+)", text, re.MULTILINE)
        if match:
            return int(match.group(1), 0)

    raise BindingError(f"unknown key name {name!r}")


def encode(binding: Binding) -> tuple[int, object]:
    """Translate a Binding into a (action_type, payload) pair."""
    if binding.type == "disabled":
        # ADR-0003: never write ACTION_NONE, which corrupts G502 Hero buttons.
        # A special action that does nothing useful is the safe substitute.
        return ACTION_SPECIAL, SPECIAL_BASE + SPECIAL_ACTIONS["resolution-default"]

    if binding.type == "button":
        number = int(binding.value)
        if not 1 <= number <= 30:
            raise BindingError(f"button number {number} is out of range")
        return ACTION_BUTTON, number

    if binding.type == "special":
        name = str(binding.value)
        if name not in SPECIAL_ACTIONS:
            raise BindingError(f"unknown special action {name!r}")
        return ACTION_SPECIAL, SPECIAL_BASE + SPECIAL_ACTIONS[name]

    if binding.type == "key":
        return ACTION_KEY, _keycode(str(binding.value))

    if binding.type == "macro":
        return ACTION_MACRO, _encode_macro(str(binding.value))

    raise BindingError(f"unsupported binding type {binding.type!r}")


def _encode_macro(spec: str) -> list[tuple[int, int]]:
    """Encode a macro spec into (event_type, value) pairs.

    The spec is a space-separated sequence of tokens:
      `KEY_A`   press and release
      `+KEY_A`  press only
      `-KEY_A`  release only
      `t300`    wait 300 ms

    The G502 accepts a chord (press modifiers, press key, release key, release
    modifiers) but rejects timed sequences at commit time, so waits are
    encoded but will fail on this hardware.
    """
    events: list[tuple[int, int]] = []
    for token in spec.split():
        if token.startswith("t") and token[1:].isdigit():
            events.append((MACRO_WAIT, int(token[1:])))
        elif token.startswith("+"):
            events.append((MACRO_KEY_PRESS, _keycode(token[1:])))
        elif token.startswith("-"):
            events.append((MACRO_KEY_RELEASE, _keycode(token[1:])))
        else:
            code = _keycode(token)
            events.append((MACRO_KEY_PRESS, code))
            events.append((MACRO_KEY_RELEASE, code))

    if not events:
        raise BindingError("macro must contain at least one event")
    if len(events) > 256:
        raise BindingError("macro exceeds the 256-event limit")
    return events
