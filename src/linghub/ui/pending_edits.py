"""Edits held in the window until Save, and thrown away by Discard.

The window used to commit each kind of edit differently: a binding was written
to the daemon the moment the editor's Apply was pressed, while DPI and lighting
each had their own Save button. That made "discard my changes" impossible to
offer honestly, because binding edits had already left.

This module holds every pending edit for one profile — bindings, DPI slots,
report rate, lighting — and flushes them in one go. Nothing reaches the daemon
until `save()`, so Discard can put the window back to what the config says.

It is deliberately not a copy of the profile: it records only what changed, so
a field the user never touched is never written. That keeps Save from
overwriting a change another client made in the meantime.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BindingEdit:
    """One button's pending binding. `kind` of "disabled" means unassigned."""

    index: int
    kind: str
    value: object = None


@dataclass
class PendingEdits:
    """What the window has changed but not yet saved, for one profile.

    Every field is optional: an untouched section is None and is not written.
    """

    profile: str
    bindings: dict[int, BindingEdit] = field(default_factory=dict)
    # (dpi, is_default, is_disabled) per slot, in slot order.
    resolutions: list[tuple[int, bool, bool]] | None = None
    report_rate: int | None = None
    # The lighting panel's four values, or None when untouched.
    leds: dict | None = None

    @property
    def dirty(self) -> bool:
        """True when anything is pending."""
        return bool(
            self.bindings
            or self.resolutions is not None
            or self.report_rate is not None
            or self.leds is not None
        )

    @property
    def has_resolutions(self) -> bool:
        """True when the DPI table or report rate has a staged edit."""
        return self.resolutions is not None

    @property
    def has_leds(self) -> bool:
        """True when lighting has a staged edit."""
        return self.leds is not None

    def set_binding(self, index: int, kind: str, value: object = None) -> None:
        self.bindings[index] = BindingEdit(index, kind, value)

    def set_resolutions(self, slots: list[tuple[int, bool, bool]], rate: int) -> None:
        self.resolutions = list(slots)
        self.report_rate = rate or None

    def set_leds(self, mode: str, brightness: int, duration: int, color) -> None:
        self.leds = {
            "mode": mode,
            "brightness": brightness,
            "duration": duration,
            "color": tuple(color),
        }

    def clear(self) -> None:
        """Forget everything pending, after a save or a discard."""
        self.bindings.clear()
        self.resolutions = None
        self.report_rate = None
        self.leds = None


class PendingEditsFor:
    """The pending edits for whichever profile the window is editing.

    Switching profiles with unsaved changes is refused by the window rather
    than handled here: holding edits for several profiles at once would mean
    two places remembering what the config says, and the config is the single
    source of truth (ADR-0004).
    """

    def __init__(self):
        self._edits: PendingEdits | None = None

    def for_profile(self, name: str) -> PendingEdits:
        """The pending edits for `name`, starting empty if it is a new one."""
        if self._edits is None or self._edits.profile != name:
            self._edits = PendingEdits(profile=name)
        return self._edits

    @property
    def dirty(self) -> bool:
        return self._edits is not None and self._edits.dirty

    def clear(self) -> None:
        if self._edits is not None:
            self._edits.clear()
