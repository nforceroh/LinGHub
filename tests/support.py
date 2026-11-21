"""Shared helpers for the UI tests.

`make_window` builds a MainWindow without a display: the constructor builds
the whole widget tree, which needs one, but the tests only need the fields the
methods they exercise touch. That list used to be copy-pasted into five test
classes and drifted; one factory keeps it in one place.

`has_cairo` is the guard the GTK tests skip on. It lives here because two test
modules need it, and two copies of a dependency probe drift.
"""

from __future__ import annotations


def has_cairo() -> bool:
    """True when cairo and GTK 4 can be imported, so the widget tests can run."""
    try:
        import cairo  # noqa: F401
        import gi

        gi.require_version("Gtk", "4.0")
    except (ImportError, ValueError):
        return False
    return True


def _default_schedule(coro, on_error=None):
    """Schedule on the running loop, for tests that drive one with asyncio.run.

    Production passes `run_and_report`, which uses the GTK-driven loop. A test
    that calls `asyncio.run` has a different loop, so the factory defaults to
    the running one; the window's own default is untouched.
    """
    import asyncio

    task = asyncio.ensure_future(coro)

    def _done(t):
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None and on_error is not None:
            on_error(exc)

    task.add_done_callback(_done)
    return task


def view(
    *,
    active: str = "desktop",
    profiles: tuple[str, ...] = ("desktop", "world-of-tanks", "star-citizen"),
    leds=None,
):
    """A DaemonView, for tests that apply one to an existing window.

    The poll delivers a view; a test that simulates a poll builds one of these
    rather than hand-rolling the two-level dataclass.
    """
    from linghub.daemon_view import DaemonView, ProfileView, ViewState

    return DaemonView(
        state=ViewState(
            active_profile=active,
            profiles=profiles,
            desktop_profile="desktop",
        ),
        profile=ProfileView(leds=leds or {}),
    )


def make_window(
    *,
    active: str = "desktop",
    profiles: tuple[str, ...] = ("desktop", "world-of-tanks", "star-citizen"),
    editing: str | None = None,
    panels: bool = False,
):
    """A MainWindow with the fields its methods read, and nothing else.

    `panels` builds the LED and DPI panels, which the tests that exercise
    dirty-state need and the rest do not.
    """
    from gi.repository import Adw, Gtk

    from linghub.daemon_view import ViewState
    from linghub.ui.window import MainWindow

    window = MainWindow.__new__(MainWindow)
    Adw.ApplicationWindow.__init__(window)
    window._schedule = _default_schedule

    window._state = ViewState()
    window._title = Adw.WindowTitle(title="t")
    window._status = Gtk.Label()
    window._banner = Adw.Banner()
    from linghub import version

    window._daemon_version = version.DaemonVersion.not_running()
    from linghub.ui.profile_selector import ProfileSelector

    window._selector = ProfileSelector(
        on_chosen=lambda name: None, on_manage=lambda: None
    )
    from linghub.ui.device_card import DeviceCard

    window._card = DeviceCard()
    # The stack needs both children and a visible one, or get_visible_child_name
    # returns None and the home-screen tests cannot tell which view is showing.
    window._stack = Gtk.Stack()
    window._stack.add_named(Gtk.Label(label="home"), "home")
    window._stack.add_named(Gtk.Label(label="editor"), "editor")
    window._stack.set_visible_child_name("home")
    window._back_button = Gtk.Button()
    window._back_button.set_visible(False)
    window._table_rows = {}
    window._binding_rows = {}
    window._bindings = {}
    window._view = None
    window._refresh_task = None
    window._refresh_pending = False
    from linghub.ui.daemon_write import DaemonWrite
    from linghub.ui.pending_edits import PendingEditsFor

    window._writes = DaemonWrite(window._refresh_now)
    window._pending = PendingEditsFor()
    window._save_button = Gtk.Button()
    window._discard_button = Gtk.Button()
    window._selected_button = None
    window._editing = editing

    if panels:
        from linghub.ui.dpi_panel import DpiPanel
        from linghub.ui.led_panel import LedPanel

        window._led_panel = LedPanel(on_save=lambda *a: None)
        window._dpi_panel = DpiPanel(on_save=lambda *a: None)
    else:
        window._led_panel = None
        window._dpi_panel = None

    window._apply_view(view(active=active, profiles=profiles))
    return window
