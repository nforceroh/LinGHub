"""Detect changes to the config file.

Polling the file's stat signature is enough here: the daemon already ticks on
an interval, and a hand-edited config does not change often enough to justify
an inotify dependency.

The signature is (mtime_ns, size, inode). Comparing for inequality rather than
"newer than" matters: an editor that preserves mtime, or a coarse timestamp,
would otherwise hide a change.
"""

from __future__ import annotations

from pathlib import Path


class ConfigWatcher:
    """Report whether the config file has changed since the last check."""

    def __init__(self, path: Path | str):
        self._path = Path(path)
        self._signature: tuple[int, int, int] | None = None

    def _current_signature(self) -> tuple[int, int, int] | None:
        try:
            stat = self._path.stat()
        except OSError:
            return None
        return (stat.st_mtime_ns, stat.st_size, stat.st_ino)

    def changed(self) -> bool:
        """True if the file differs from the last observed state.

        The first call always reports a change, so the caller loads the config
        once at startup without special-casing it.
        """
        current = self._current_signature()
        if current == self._signature:
            return False
        self._signature = current
        return True

    def reset(self) -> None:
        """Forget the observed state, so the next check reports a change."""
        self._signature = None

    def resync(self) -> None:
        """Accept the current file state without reporting a change.

        Used after the daemon writes the file itself: the contents on disk are
        already what it has in memory, so treating the write as an external
        edit would cause a pointless reload.
        """
        self._signature = self._current_signature()
