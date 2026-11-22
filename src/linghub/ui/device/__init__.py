"""The device panels: DPI presets and LIGHTSYNC.

Each panel stages its edits and reports them to the window; the rules the
panels share live in `rules`.
"""

from .dpi_panel import DpiPanel
from .led_panel import LedPanel

__all__ = ["DpiPanel", "LedPanel"]
