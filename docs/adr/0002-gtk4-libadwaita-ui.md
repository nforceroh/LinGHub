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
