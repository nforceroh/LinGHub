"""An edit held until Save, so nothing reaches the mouse while it is adjusted.

Both panels stage their edits: a slider fires on every pixel, so writing as
you drag meant one config write and two hardware commits per pixel. Each panel
therefore keeps a baseline, reports whether it is dirty, and offers Save and
Revert. That lifecycle was implemented twice, and the copies had already
drifted — one reported its hint through a label, the other through a status
line, and their `revert` bodies differ because they restore different widgets.

So this module owns the part that is genuinely shared: the baseline, the dirty
decision, the save guard, and the guard that stops a programmatic restore from
marking the panel dirty again. Each panel keeps its widgets, its `values()`,
and its own `restore()` body — which is why this is a held object rather than
a base class. A base class would invite a `revert` implementation that only
fits one panel.

The `restoring()` context manager is the piece worth owning here: forgetting
the `finally` leaves the panel permanently unable to notice edits, and both
copies had to get it right.
"""

from __future__ import annotations

import contextlib
from typing import Callable


class StagedEdit:
    """The baseline and the save/revert rule for one panel's staged values.

    `values` returns everything the panel edits, as one comparable value.
    `on_save` receives those values when Save is pressed. `on_restore`
    receives the baseline when Revert is pressed, and is where the panel puts
    them back into its widgets. `on_changed` is told whether the panel is
    dirty, so it can enable its buttons and set its hint.
    """

    def __init__(
        self,
        values: Callable[[], object],
        *,
        on_save: Callable[[object], None],
        on_restore: Callable[[object], None],
        on_changed: Callable[[bool], None],
    ):
        self._values = values
        self._on_save = on_save
        self._on_restore = on_restore
        self._on_changed = on_changed
        self._baseline: object | None = None
        self._restoring = False

    @property
    def restoring_now(self) -> bool:
        """True while the panel is putting values back into its widgets.

        A panel that reacts to a widget signal by changing other widgets needs
        to know, so it does not treat its own restore as a user edit.
        """
        return self._restoring

    @property
    def dirty(self) -> bool:
        """True when the panel differs from what was last loaded or saved."""
        return self._baseline is not None and self._values() != self._baseline

    def edited(self) -> None:
        """A control changed: record it, but do not touch the mouse.

        Ignored while a restore is in progress, because putting values back
        into widgets fires the same signals a user edit does.
        """
        if self._restoring:
            return
        self._on_changed(self.dirty)

    def save(self) -> None:
        """Hand the staged values to the panel, unless nothing changed."""
        if not self.dirty:
            return
        self._on_save(self._values())

    def mark_saved(self) -> None:
        """Accept the current values as the saved state."""
        self._baseline = self._values()
        self._on_changed(self.dirty)

    def revert(self) -> None:
        """Throw away unsaved edits and go back to the saved values."""
        if self._baseline is None:
            return
        with self.restoring():
            self._on_restore(self._baseline)
        self._on_changed(self.dirty)

    @contextlib.contextmanager
    def restoring(self):
        """Suppress `edited()` while the panel puts values back into widgets.

        A context manager rather than a flag the panel sets, because a missed
        `finally` would leave the panel unable to notice edits at all.
        """
        self._restoring = True
        try:
            yield
        finally:
            self._restoring = False
