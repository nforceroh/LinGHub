# LinGHub

A profile manager for the Logitech G502 family on Linux. It edits named profiles
— button bindings, DPI table, LED settings and report rate — and loads the right
one into the mouse when a game starts.

LinGHub talks to [ratbagd](https://github.com/libratbag/libratbag) over the
system D-Bus. It does not use `ratbagctl`, and it does not create virtual input
devices: every binding is written to the mouse's own memory, so games see real
hardware events.

## Status

Early. The hardware client and CLI work; game detection and the UI are in
progress.

## Requirements

- Linux with ratbagd running (Fedora: `libratbag-ratbagd`)
- Python 3.11+
- A G502 variant supported by libratbag

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

## Usage

```bash
linghub list          # list hardware profiles
linghub switch 1      # activate profile 1
linghub detect        # report which configured game is running
linghub run           # run the daemon in the foreground
linghub ui            # open the graphical interface
```

`switch` reports that ratbagd has queued a commit. Commits are asynchronous, so
that message does not confirm the hardware write succeeded.

## Graphical interface

`linghub ui` opens a GTK4 window showing the mouse diagram, the profile list and
a table of every button with what it currently does. Clicking a hotspot on the
diagram selects that button; activating a profile in the list loads it onto the
mouse.

Clicking a row in the button table opens a dialog for changing that button's
binding: a single key, a modifier chord, a mouse function such as DPI up,
another mouse button, or nothing. The change goes to the daemon, which writes the
config and pushes it to the mouse. The daemon recognises its own write and does
not mistake it for a hand edit.

Below the button table is a lighting panel: colour, effect, brightness and
speed, applied to the whole profile. The G502 has two LED zones, but they read
as one strip, so the panel drives them together; the daemon writes the same
values to each. Effects are `off`, `fixed colour`, `cycle` and `breathing`, and
only the looping ones have a speed.

The dialog only offers bindings the hardware can actually encode. `second-mode`
is deliberately absent because libratbag rejects it on the G502 (issue #1798); if
a config already contains it, the table shows the raw name so it can be replaced.

The UI talks to the daemon over D-Bus, so the daemon must be running. It needs
PyGObject, which on Fedora is the `python3-gobject` package:

```bash
sudo dnf install python3-gobject
```

If the virtualenv was created without system packages, enable them so `gi` is
importable:

```bash
sed -i 's/include-system-site-packages = false/include-system-site-packages = true/' \
  .venv/pyvenv.cfg
```

## Running as a service

```bash
./scripts/install-service.sh     # install and start the user service
./scripts/uninstall-service.sh   # stop and remove it
```

The daemon watches for games and loads the matching profile into slot 1,
restoring the desktop profile into slot 0 when the last game exits. It reloads
its config when the file changes, and keeps the previous config if an edit is
invalid rather than exiting.

Detection polls `/proc` every couple of seconds. When
[Feral GameMode](https://github.com/FeralInteractive/gamemode) is running, its
registration signals also trigger an immediate check, so games launched through
`gamemoderun` switch without waiting for the next poll. GameMode is optional:
games that do not register with it are still detected by polling.

```bash
systemctl --user status linghub.service
journalctl --user -u linghub.service -f
```

## D-Bus interface

The daemon publishes `org.linghub.Manager` on the session bus at
`/org/linghub/Manager`, so a UI can read state and request changes without
editing the config file.

| Member | Kind | Meaning |
| --- | --- | --- |
| `ListProfiles` | method → `as` | Every profile name in the config |
| `LoadProfile(s)` | method → `b` | Load a profile now; false if it does not exist |
| `Reload` | method → `b` | Re-read the config file |
| `ActiveProfile` | property `s` | Profile currently on the mouse, empty if unknown |
| `DetectedGame` | property `s` | Game currently detected, empty if none |
| `DesktopProfile` | property `s` | Profile used when no game is running |
| `ProfileChanged(s)` | signal | A profile was loaded onto the mouse |
| `GameDetected(s)` | signal | A game started being detected |
| `GameExited(s)` | signal | A detected game stopped running |

A manual `LoadProfile` lasts until the detected game changes, then detection
takes over again.

```bash
busctl --user call org.linghub.Manager /org/linghub/Manager \
  org.linghub.Manager ListProfiles
```

## Configuration

The daemon reads `~/.config/linghub/config.json`. See
[config.example.json](config.example.json) for the shape. One file holds every
profile plus application settings (ADR-0004).

## Documentation

- [Button map](docs/button-map.md) — manual number, G-name and ratbag index for
  every button, plus the supported variants
- [Glossary](GLOSSARY.md) — the vocabulary this project uses
- [Architecture decisions](docs/adr/) — why the design is the way it is

## Legacy scripts

`utils/` holds the scripts that predate LinGHub. They use `ratbagctl` and their
own `g502-profiles.json`, which is **not** the format LinGHub reads. They are
kept for reference and will be removed.

## Development

```bash
.venv/bin/python -m unittest discover -s tests -t .
```
