"""Domain model for LinGHub.

Entities here are pure: they hold no knowledge of D-Bus, /proc, or the
filesystem. See GLOSSARY.md for the vocabulary.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class Game:
    """A program that should cause a profile to become active.

    `executable` is matched case-insensitively against the basename of a
    process's argv[0], so `WorldOfTanks.exe` matches the Wine process whose
    argv[0] is `C:\\Games\\World_of_Tanks_NA\\win64\\WorldOfTanks.exe`.
    """

    executable: str

    def __post_init__(self) -> None:
        if not self.executable.strip():
            raise ValueError("game executable must not be empty")

    @property
    def key(self) -> str:
        return self.executable.casefold()


@dataclass(frozen=True)
class Binding:
    """What a single mouse button does when pressed."""

    type: str
    value: object = None

    VALID_TYPES = ("button", "key", "special", "macro", "disabled")

    def __post_init__(self) -> None:
        if self.type not in self.VALID_TYPES:
            raise ValueError(
                f"unknown binding type {self.type!r}; expected one of {self.VALID_TYPES}"
            )


@dataclass(frozen=True)
class Profile:
    """A named set of mouse settings, loaded into a slot when activated."""

    name: str
    games: tuple[Game, ...] = ()
    report_rate: int | None = None
    resolutions: tuple[dict, ...] = ()
    bindings: dict[int, Binding] = field(default_factory=dict)
    leds: tuple[dict, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("profile name must not be empty")

    @property
    def is_desktop(self) -> bool:
        return not self.games

    def with_binding(self, index: int, binding: Binding | None) -> "Profile":
        """A copy with one button's binding replaced, or removed if None.

        The dataclass is frozen but `bindings` is a dict, so mutating it in
        place would edit a "frozen" value. Going through a copy keeps every
        profile value immutable and makes a change easy to reason about.
        """
        updated = dict(self.bindings)
        if binding is None:
            updated.pop(index, None)
        else:
            updated[index] = binding
        return replace(self, bindings=updated)
