"""What the window should show, decided without a widget.

The window used to decide these things inline: which profile the panels edit,
what each profile row's subtitle says, what each button row's "does" column
says. All of it is pure — it depends only on daemon state and the current
selection — but it lived behind a GTK widget, so the only way to test it was to
construct the widget by hand and poke its fields.

Keeping the decisions here means the window is left with widget construction
and event wiring, and the rules can be tested directly.
"""

from __future__ import annotations

from dataclasses import dataclass

from .binding_labels import describe_binding


@dataclass(frozen=True)
class ProfileRow:
    """One row of the profile list."""

    name: str
    on_the_mouse: bool
    editing: bool
    is_desktop: bool

    @property
    def subtitle(self) -> str:
        """Two different facts, so two different markers.

        The tick means "on the mouse"; the subtitle means "shown in the
        panels". They are separate because a profile can be edited without
        being loaded.
        """
        parts = []
        if self.on_the_mouse:
            parts.append("on the mouse")
        if self.editing:
            parts.append("editing")
        return " · ".join(parts)


def editing_profile(state, selection: str | None) -> str | None:
    """The profile the panels show and edit.

    The selection wins, so a gaming profile can be edited without being
    loaded. Falls back to what is loaded, then the desktop profile.
    """
    if selection and selection in state.profiles:
        return selection
    for candidate in (state.active_profile, state.desktop_profile):
        if candidate and candidate in state.profiles:
            return candidate
    return state.profiles[0] if state.profiles else None


def profile_rows(state, selection: str | None) -> list[ProfileRow]:
    """Every profile as a row, in config order."""
    editing = editing_profile(state, selection)
    return [
        ProfileRow(
            name=name,
            on_the_mouse=name == state.active_profile,
            editing=name == editing,
            is_desktop=name == state.desktop_profile,
        )
        for name in state.profiles
    ]


def binding_label(bindings: dict, index: int, pending=None) -> str:
    """What the "Does" column says for one button.

    A staged edit wins over the saved binding, so the table shows what the
    profile will do once Apply is pressed, not what it does now. Pending
    labels are marked with a bullet so the staged state is visible.
    """
    if pending is not None and index in pending:
        edit = pending[index]
        return "* " + describe_binding(edit.kind, edit.value)
    kind, value = bindings.get(index, ("", None))
    return describe_binding(kind, value) if kind else "—"


def binding_labels(bindings: dict, indices) -> dict[int, str]:
    """The "Does" column for every button, keyed by ratbag index."""
    return {index: binding_label(bindings, index) for index in indices}


def diagram_binding_label(bindings: dict, index: int) -> str:
    """A compact, truthful label for a diagram leader line."""
    kind, _value = bindings.get(index, ("", None))
    if kind in ("key", "special", "button", "disabled"):
        label = binding_label(bindings, index)
        return label if label != "—" else "Nothing"
    from .buttonmap import describe
    return describe(index)
