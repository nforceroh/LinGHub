"""Decide which game, if any, is running.

Detection is deliberately explainable: every candidate process is recorded
with the rule that matched it or the reason it was rejected, so `--explain`
can show why a game was or was not detected.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.profile import Game, Profile
from .processes import ProcessInfo, deduplicate, discover_processes


@dataclass(frozen=True)
class Match:
    """A process that matched a configured game."""

    game: Game
    profile: Profile
    process: ProcessInfo


@dataclass(frozen=True)
class Rejection:
    """A process that was considered and why it did not match."""

    process: ProcessInfo
    reason: str


@dataclass
class Detection:
    """The outcome of one detection pass."""

    matches: list[Match] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)
    considered: int = 0

    @property
    def game(self) -> Match | None:
        """The game to act on, or None.

        When several games are running the first match in profile order wins,
        so the result is stable rather than dependent on /proc iteration order.
        """
        return self.matches[0] if self.matches else None


def _game_index(profiles: list[Profile]) -> list[tuple[Game, Profile]]:
    """Flatten profiles into (game, profile) pairs, preserving profile order."""
    return [(game, profile) for profile in profiles for game in profile.games]


def detect(
    profiles: list[Profile],
    processes: list[ProcessInfo] | None = None,
) -> Detection:
    """Match running processes against the games configured in `profiles`."""
    if processes is None:
        processes = deduplicate(discover_processes())

    index = _game_index(profiles)
    result = Detection(considered=len(processes))

    if not index:
        result.rejections = [
            Rejection(process, "no games configured") for process in processes
        ]
        return result

    for process in processes:
        executable = process.executable_name.casefold()
        matched = next(
            ((game, profile) for game, profile in index if game.key == executable),
            None,
        )
        if matched is None:
            result.rejections.append(
                Rejection(process, f"executable {process.executable_name!r} is not a configured game")
            )
            continue
        game, profile = matched
        result.matches.append(Match(game=game, profile=profile, process=process))

    return result
