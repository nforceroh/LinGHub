"""Keep the main window usable on any monitor.

Two rules live here: what size a new window opens at, and what happens the
first time a remembered-larger-than-screen window is mapped. Both are pure
window-examining policies — they read the display, not the app's state — so
they take the window as a Gtk.Window and never touch the daemon, the panels
or the profile state.
"""

from __future__ import annotations

from gi.repository import Gdk, Gtk

# The size the layout is designed for. Anything smaller and the bottom row
# starts to scroll; anything larger is wasted space.
WANTED_SIZE = (1140, 840)

# The share of a monitor the window may claim: the rest goes to the desktop's
# own panels and the window's shadow.
SCREEN_SHARE = (0.92, 0.88)


def _clamped_to_screen(width: int, height: int, geometry) -> tuple[int, int]:
    """(width, height) capped to the monitor's share of the screen."""
    share_width, share_height = SCREEN_SHARE
    return (
        min(width, int(geometry.width * share_width)),
        min(height, int(geometry.height * share_height)),
    )


def preferred_size(wanted: tuple[int, int]) -> tuple[int, int]:
    """The window size to open at, clamped to the screen it opens on.

    The layout wants 1140x840, but a 1366x768 laptop has about 745 usable
    pixels of height, and a window taller than the screen hides its own
    bottom row. Asking for the layout's size and letting the monitor cap it
    keeps the window fully visible on any screen.
    """
    wanted_width, wanted_height = wanted
    display = Gdk.Display.get_default()
    if display is None:
        return wanted_width, wanted_height
    monitors = display.get_monitors()
    if monitors.get_n_items() == 0:
        return wanted_width, wanted_height
    geometry = monitors.get_item(0).get_geometry()
    return _clamped_to_screen(wanted_width, wanted_height, geometry)


def connect_first_map(window: Gtk.Window) -> None:
    """Put the window fully on-screen the first time it is shown.

    The desktop remembers a window position per application id, and a position
    saved when the window's minimum width exceeded the screen keeps restoring
    half off-screen. Maximizing overrides it; the user can unmaximize to
    whatever size they want afterwards.
    """
    window.connect("map", _on_first_map)


def _on_first_map(window) -> None:
    _fit_to_screen(window)
    if not window.is_maximized():
        window.maximize()


def _fit_to_screen(window: Gtk.Window) -> None:
    """Shrink a window that is larger than the screen it opened on.

    The desktop remembers a window's size per application id, so a size that
    was correct for an older, taller layout is restored over the default and
    can leave the window taller than the screen, hiding its own bottom row.
    The remembered size is only a starting point: if it does not fit, the
    screen wins.
    """
    surface = window.get_surface()
    display = Gdk.Display.get_default()
    if surface is None or display is None:
        return
    monitor = display.get_monitor_at_surface(surface)
    if monitor is None:
        return
    geometry = monitor.get_geometry()
    width, height = window.get_width(), window.get_height()
    if width <= geometry.width and height <= geometry.height:
        return
    window.set_default_size(*_clamped_to_screen(width, height, geometry))
