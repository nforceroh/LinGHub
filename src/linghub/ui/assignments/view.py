"""The Assignments view: diagram, sidebar and bindings table as one module.

The window used to own this view's state directly — the table rows, the
binding labels, the selected button, the staging of a chosen assignment — so
its tests had to build the whole window to check that a drop highlighted a
row or staged a binding. That state is one concept: what the Assignments view
is showing and editing.

This module owns it. The window hands it the daemon's bindings, the pending
edits and the profile being edited, and asks it to refresh; the module answers
with the user's intent through two callbacks — `on_stage` when an assignment
is chosen, `on_dirty_changed` so the window can enable Apply. The dialog and
the daemon stay outside: staging records intent, the window decides what a
staged edit is worth.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk

from .. import presentation
from .sidebar import AssignmentSidebar
from .editor import BindingEditor
from .labels import describe_binding
from ..buttonmap import BUTTONS, DIAGRAM_IMAGE, describe, manual_number
from .diagram import MouseDiagram

IMAGE = DIAGRAM_IMAGE


class AssignmentsView(Gtk.Paned):
    """Sidebar, diagram and bindings table, with the selection and staging.

    The interface is four calls: `refresh` after the daemon or the pending
    edits change, `set_selected` when a button is picked, `open_editor` for
    the dialog, and `widget` for placement. Everything else — rows, labels,
    highlight, drop targets — is implementation.
    """

    def __init__(self, on_stage, on_status):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        self.set_wide_handle(True)
        # 390px: wide enough for the four group tabs and the choice labels
        # to read without ellipsizing. Narrower defaults squeezed the tab row
        # and left every row caption cut off until the divider was dragged.
        self.set_position(390)

        self._on_stage = on_stage
        self._on_status = on_status
        self._selected: int | None = None
        self._bindings: dict = {}
        self._pending_bindings: dict = {}

        self._sidebar = AssignmentSidebar(on_chosen=self._on_chosen)

        right = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        right.set_wide_handle(True)
        right.set_position(430)
        right.set_start_child(self._build_diagram_pane())

        table_scroller = Gtk.ScrolledWindow()
        table_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        table_scroller.set_vexpand(True)

        table_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        table_box.set_margin_top(8)
        table_box.set_margin_bottom(12)
        table_box.set_margin_start(12)
        table_box.set_margin_end(12)
        table_box.append(self._section_label("Bindings"))
        table_box.append(self._build_button_table())
        table_scroller.set_child(table_box)
        right.set_end_child(table_scroller)

        self.set_start_child(self._sidebar)
        self.set_end_child(right)

    # --- interface --------------------------------------------------------

    def refresh(self, bindings: dict, pending_bindings: dict) -> None:
        """Show the saved bindings with the staged edits on top of them."""
        self._bindings = bindings
        self._pending_bindings = pending_bindings
        for index, widget in self._table_rows.items():
            if index == self._selected:
                widget.add_css_class("accent")
            else:
                widget.remove_css_class("accent")

            label = self._binding_rows.get(index)
            if label is not None:
                label.set_text(
                    presentation.binding_label(bindings, index, pending_bindings)
                )
        if self._diagram is not None:
            self._diagram.set_binding_labels(
                {
                    index: presentation.diagram_binding_label(bindings, index)
                    for index in [spot.index for spot in BUTTONS]
                }
            )

    def set_selected(self, index: int | None) -> None:
        """Pick a button, on the diagram and in the table."""
        self._selected = index
        if self._diagram is not None:
            self._diagram.set_selected(index)
        self.refresh(self._bindings, self._pending_bindings)

    def selected(self) -> int | None:
        """The button the user last picked, or None."""
        return self._selected

    def open_editor(self, parent, profile: str, on_apply) -> None:
        """Open the binding editor for the selected button.

        `on_apply(index, kind, value)` answers like _start_binding_write:
        a truthy result closes the dialog, a string shows it as an error.
        """
        if self._selected is None:
            return
        kind, value = self._bindings.get(self._selected, ("disabled", None))
        BindingEditor(
            parent=parent,
            button_index=self._selected,
            kind=kind or "disabled",
            value=value,
            on_apply=on_apply,
        ).present()

    # --- construction -----------------------------------------------------

    def _build_diagram_pane(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)

        if IMAGE.exists():
            self._diagram: MouseDiagram | None = MouseDiagram(str(IMAGE))
            self._diagram.connect("button-selected", self._on_button_selected)
            self._diagram.connect("assignment-dropped", self._on_dropped)
            # No Frame: it drew a border and a filled background around the
            # image, which has a transparent background of its own. The image
            # sits directly in the pane, so the UI's background shows through.
            # Top-aligned: the image cannot grow to fill a tall pane without
            # distorting, so the space it leaves belongs at the bottom rather
            # than split above and below it.
            self._diagram.set_valign(Gtk.Align.START)
            box.append(self._diagram)
        else:
            self._diagram = None
            box.append(Gtk.Label(label=f"Diagram not found: {IMAGE}"))

        return box

    def _build_button_table(self) -> Gtk.Widget:
        """Every button: manual number, function and ratbag index.

        The diagram labels circles with ratbag indices, so `Ratbag` is the
        column to read against the picture. `Manual` is only there to help
        someone holding the printed manual.
        """
        grid = Gtk.Grid()
        grid.set_column_spacing(18)
        # 2px between rows: eleven rows at 6px cost 66px of pure gap, and the
        # table is the tallest thing in the pane.
        grid.set_row_spacing(2)
        grid.set_margin_top(4)

        titles = ("Manual", "Function", "Does", "Ratbag")
        for column, title in enumerate(titles):
            label = Gtk.Label(label=title, xalign=0 if column != 3 else 1)
            label.add_css_class("dim-label")
            label.add_css_class("caption")
            grid.attach(label, column, 0, 1, 1)

        self._table_rows: dict[int, Gtk.Widget] = {}
        self._binding_rows: dict[int, Gtk.Widget] = {}

        for row, spot in enumerate(BUTTONS, start=1):
            manual = Gtk.Label(label=manual_number(spot.index), xalign=0)
            manual.add_css_class("dim-label")
            function = Gtk.Label(label=describe(spot.index), xalign=0)
            # No hexpand: it stretched the Function column across the pane and
            # pushed Does and Ratbag to the far edge, leaving a wide gap
            # between Function and Does. The columns now sit at their natural
            # widths, close together.
            does = Gtk.Label(label="—", xalign=0)
            ratbag = Gtk.Label(label=str(spot.index), xalign=1)
            ratbag.add_css_class("dim-label")

            widgets = (manual, function, does, ratbag)
            for column, widget in enumerate(widgets):
                grid.attach(widget, column, row, 1, 1)

            # The whole row is the click target, so a narrow label is not the
            # only way to open the editor. A controller can only belong to one
            # widget, so each label gets its own.
            for widget in widgets:
                click = Gtk.GestureClick()
                click.connect(
                    "released",
                    lambda _g, _n, _x, _y, i=spot.index: self._on_row_clicked(i),
                )
                widget.add_controller(click)

            self._table_rows[spot.index] = function
            self._binding_rows[spot.index] = does

        return grid

    def _section_label(self, text: str) -> Gtk.Label:
        label = Gtk.Label(label=text, xalign=0)
        label.add_css_class("heading")
        return label

    # --- events -----------------------------------------------------------

    def _on_row_clicked(self, index: int) -> None:
        self.set_selected(index)
        self._on_status(f"Selected: {describe(index)}")

    def _on_button_selected(self, _diagram, index: int) -> None:
        self.set_selected(index)
        self._on_status(f"Selected: {describe(index)}")

    def _on_dropped(self, _diagram, index: int, choice) -> None:
        """A sidebar choice dropped on a hotspot assigns that button."""
        self.set_selected(index)
        self._on_chosen(choice.kind, choice.value)

    def _on_chosen(self, kind: str, value: object) -> None:
        """Stage a sidebar choice for the selected button."""
        if self._selected is None:
            self._on_status(
                "Select a button on the diagram or in the bindings table first."
            )
            return
        if kind == "disabled":
            assigned = "Nothing"
        else:
            assigned = describe_binding(kind, value)
        self._on_stage(self._selected, kind, value)
        self._on_status(
            f"{describe(self._selected)} will do {assigned} — press Apply."
        )
