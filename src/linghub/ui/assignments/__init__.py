"""The Assignments view and its vocabulary.

`view` is the interface the window composes; `catalogue` owns what a button
can be assigned; `labels` describes what a stored binding is called. The
sidebar, editor and diagram are the view's implementation.
"""

from .view import AssignmentsView

__all__ = ["AssignmentsView"]
