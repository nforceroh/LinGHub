"""The app version: which build of LinGHub this process loaded.

Read from git when the process runs from a clone, since an editable install
records its version once, at `pip install -e`, and goes stale with the next
commit. Without a clone, the version baked in at build time is used. See
ADR-0009 for why.

The daemon, tray and window each loaded the code when they started, so each
has its own version, fixed at first read; `describe` is what a client says
when the daemon's differs from its own.
"""

from __future__ import annotations

import enum
import functools
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

UNKNOWN = "unknown"

_DESCRIBE = re.compile(r"^v(\d+\.\d+\.\d+)-(\d+)-g([0-9a-f]+)(-dirty)?$")
_HASH = re.compile(r"^([0-9a-f]+)(-dirty)?$")

Git = Callable[[list[str]], str]


def from_git(run: Git) -> str | None:
    """The version git describes, or None if git cannot say.

    `run` takes git's arguments and returns its trimmed output, raising if
    git fails. On a tag this is the bare release (`0.1.0`); past one, or with
    uncommitted changes, it is a local version (`0.1.0+3.g5c27eef.dirty`).
    With no tag yet, the release is 0.0.0 and the count is every commit.
    """
    try:
        described = run(["describe", "--tags", "--long", "--dirty", "--match", "v[0-9]*"])
    except (subprocess.SubprocessError, OSError):
        described = None

    if described is not None:
        match = _DESCRIBE.match(described)
        if match is None:
            return None
        release, count, commit, dirty = match.groups()
    else:
        try:
            count = run(["rev-list", "--count", "HEAD"])
            match = _HASH.match(run(["describe", "--always", "--dirty", "--abbrev=7"]))
        except (subprocess.SubprocessError, OSError):
            return None
        if match is None or not count.isdigit():
            return None
        release = "0.0.0"
        commit, dirty = match.groups()

    if count == "0" and not dirty:
        return release
    return f"{release}+{count}.g{commit}" + (".dirty" if dirty else "")


def resolve(
    *,
    clone: Path | None,
    git: Callable[[Path], str | None],
    installed: Callable[[], str | None],
) -> str:
    """Prefer git when there is a clone; otherwise the installed version."""
    if clone is not None:
        found = git(clone)
        if found is not None:
            return found
    return installed() or UNKNOWN


class DaemonVersionKind(enum.Enum):
    """Which of the four things a client can know about the daemon's version."""

    KNOWN = "known"
    PREDATES_REPORTING = "predates reporting"
    NOT_RUNNING = "not running"
    UNREADABLE = "unreadable"


@dataclass(frozen=True)
class DaemonVersion:
    """What a client knows about the daemon's version, as one value.

    Four states, each its own value rather than a sentinel that can be
    mistaken for another: a daemon too old to report a version is not the
    same as one that isn't running, and neither is the same as one that
    answered badly. `version` is set only when the kind is KNOWN.
    """

    kind: DaemonVersionKind
    version: str = ""

    @classmethod
    def known(cls, version: str) -> DaemonVersion:
        return cls(DaemonVersionKind.KNOWN, version)

    @classmethod
    def predates_reporting(cls) -> DaemonVersion:
        return cls(DaemonVersionKind.PREDATES_REPORTING)

    @classmethod
    def not_running(cls) -> DaemonVersion:
        return cls(DaemonVersionKind.NOT_RUNNING)

    @classmethod
    def unreadable(cls) -> DaemonVersion:
        return cls(DaemonVersionKind.UNREADABLE)


def describe(own: str, daemon: DaemonVersion) -> tuple[str, str | None]:
    """The daemon's version line, and a note when it differs from ours.

    The one rendering the CLI, the tray and the window share, so the three
    cannot disagree about what the daemon is running. An exact comparison:
    two processes started from the same commit with different uncommitted
    edits compare equal, which git cannot tell apart.

    An unreadable version gets no note: we do not know that it differs, and
    a failed read is not worth a banner. It still gets its own line, so the
    About dialog never calls a running daemon "not running".
    """
    if daemon.kind is DaemonVersionKind.NOT_RUNNING:
        return "Daemon  not running", None
    if daemon.kind is DaemonVersionKind.PREDATES_REPORTING:
        return "Daemon  unknown", "Daemon predates version reporting; restart it"
    if daemon.kind is DaemonVersionKind.UNREADABLE:
        return "Daemon  unreadable", None
    if daemon.version != own:
        return f"Daemon  {daemon.version}", f"Daemon is running {daemon.version}; restart it"
    return f"Daemon  {daemon.version}", None


@functools.cache
def current() -> str:
    """This process's app version, read once and then fixed.

    Call it at startup: a later first read would report whatever the clone
    holds by then, not the code this process loaded.
    """
    return resolve(clone=_clone(), git=_read_git, installed=_installed)


def _clone() -> Path | None:
    """The clone this package runs from, or None for an installed package."""
    root = Path(__file__).resolve().parents[2]
    if (root / ".git").exists() and (root / "pyproject.toml").exists():
        return root
    return None


def _read_git(clone: Path) -> str | None:
    def run(args: list[str]) -> str:
        return subprocess.run(
            ["git", "-C", str(clone), *args],
            capture_output=True, text=True, check=True, timeout=5,
        ).stdout.strip()

    return from_git(run)


def _installed() -> str | None:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("linghub")
    except PackageNotFoundError:
        return None
