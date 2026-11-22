# Use GTK4 and libadwaita for the UI, not Qt

The UI must work on both KDE Plasma and GNOME. Qt is the native toolkit on KDE,
but GTK4 and libadwaita are already installed on the target system while
PySide6 is not, and GTK4 is the toolkit most cross-desktop Linux applications
ship. We accept a non-native look on KDE in exchange for one toolkit that works
everywhere without an extra dependency.

## Considered Options

- **PySide6/Qt6** — native on KDE, but needs `qt6ct` theming to look right on
  GNOME and adds a large dependency.
- **Plain GTK4 without libadwaita** — neutral on both desktops, but every widget
  must be hand-built and the result looks dated.
- **Local web UI** — truly desktop-agnostic, but a browser tab is poor UX for a
  mouse configuration tool.

## Amendment: reaffirmed after the 2026-11-21 architecture review

The review raised the toolkit question again, prompted by the tray being a
separate process. It is worth recording why that is not a reason to move.

**The tray's separate process is a consequence of AppIndicator3, not a defect.**
PyGObject loads a GObject namespace once per process at a fixed version, so
`gi.require_version("Gtk", "3.0")` and `gi.require_version("Gtk", "4.0")`
cannot both succeed — the second raises `ValueError: Namespace Gtk is already
loaded with version 3.0`. This is process-global, not thread-local: running the
tray on a background thread does not avoid it. There is no GTK4 AppIndicator
(`libayatana-appindicator` ships GTK2 and GTK3 only), so a GTK4 tray icon is
not available. The split also gives the tray a property worth keeping: it
survives closing the main window.

**A port was costed.** The UI is 3,134 lines: 906 toolkit-independent
(`client`, `buttonmap`, `assignments/labels`, `assignments/catalogue`, `device/rules`,
`presentation`, `asyncbridge`) and 2,228 GTK4/libadwaita widget code. A port
rewrites the 2,228 and keeps the 906, plus 1,395 lines of UI tests that drive
GTK widgets directly. It is not mechanical: the window uses eleven libadwaita
widgets (`Adw.ToolbarView`, `Adw.HeaderBar`, `Adw.Banner`, `Adw.ActionRow`,
`Adw.AboutDialog`, `Adw.MessageDialog`, and others) and GTK4-only APIs
(`Gtk.DropDown`, `Gtk.StringList`, `Gtk.GestureClick`,
`Gtk.EventControllerMotion`), each of which needs a Qt equivalent designed
rather than substituted.

**GTK3 only is the worst of the three.** It would mean porting backwards to a
toolkit in maintenance mode, and losing libadwaita entirely, since libadwaita
is GTK4-only. That is the modern look this ADR chose deliberately.

**Qt6 remains the strongest alternative, and remains rejected.** It is native
on KDE, which is the desktop this project is developed on. But PySide6 is not
packaged for Fedora as `python3-pyside6`, so it would be a pip dependency
inside an RPM, which ADR-0011's wheel-based packaging makes awkward. It also
does not remove the tray problem: Qt has no AppIndicator either, so a Qt port
would still need StatusNotifierItem over D-Bus or a separate process.

**What the review did find** is a real fragility, and it is not the toolkit:
`daemon_access` imports the client's view types from `ui/`, and that is safe
only because `ui/client.py` happens to import no GTK. One `import gi` added
there for any reason would break the tray at startup with a `ValueError` at
import time. The fix is to move those types out of `ui/`, not to change
framework.

**Revisit this ADR if** libadwaita becomes a distribution burden, the UI needs
something GTK4 cannot do, or the window is being rewritten for unrelated
reasons — at which point Qt6 should be costed properly rather than dismissed.
