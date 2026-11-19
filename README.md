# LinGHub

A profile manager for the Logitech G502 family on Linux. It edits named profiles
— button bindings, DPI table, LED settings and report rate — and loads the right
one into the mouse when a game starts.

LinGHub talks to [ratbagd](https://github.com/libratbag/libratbag) over the
system D-Bus. It does not use `ratbagctl`, and it does not create virtual input
devices: every binding is written to the mouse's own memory, so games see real
hardware events.

## Status

Usable. Game detection, automatic profile switching, and a UI that edits
bindings, DPI, report rate and lighting all work and have been exercised
against a G502 Lightspeed on Fedora with World of Tanks and Star Citizen.

Not done yet: packaging (it installs from a clone), and testing on the other six
G502 variants.

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
linghub status        # what the daemon is doing, and which slot the mouse says it is on
linghub tray          # show a tray icon for switching profiles
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
speed, applied to the whole profile. Lighting is edited and then saved rather
than written as you go, because sliders fire a change per pixel — dragging one
used to mean a config write and two hardware commits for every step. Nothing
reaches the mouse until Save; Revert throws away unsaved edits. The G502 has two LED zones, but they read
as one strip, so the panel drives them together; the daemon writes the same
values to each. Effects are `off`, `fixed colour`, `cycle` and `breathing`, and
only the looping ones have a speed.

Between them, the DPI and lighting panels cover the whole profile. Both are
staged rather than live: nothing reaches the mouse until Save, and Revert throws
away unsaved edits. A refresh never overwrites unsaved edits, so a change made
elsewhere cannot discard what you are in the middle of choosing.

Profiles can be created, renamed and deleted from the buttons above the profile
list. The desktop profile cannot be deleted, and neither can the last remaining
one; the daemon refuses both rather than relying on the UI to check.

A single key can be sent two ways: as a key event, or as a macro holding one
press/release pair. They are not interchangeable — World of Tanks under Wine
ignores the key-event form — so the editor offers both, as "A single key" and
"A single key, as a macro". See [ADR-0008](docs/adr/0008-key-versus-macro.md).

The dialog only offers bindings the hardware can actually encode. `second-mode`
is deliberately absent because libratbag rejects it on the G502 (issue #1798); if
a config already contains it, the table shows the raw name so it can be replaced.

The daemon survives the mouse disappearing: a KVM switch, an unplugged cable or
a flat battery all remove the device node. It keeps detecting games, drops its
stale handle, and reconnects when the device returns. It also publishes its
D-Bus interface and starts detecting before it looks for the device, so the UI
and tray still show the configured profiles while the mouse is away. The hidraw node
number changes on reconnect, so the daemon checks on every pass that its device
path still names the G502, and finds it again when it doesn't.

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

## Notifications and the tray

The daemon sends a desktop notification when it switches profile, using
`org.freedesktop.Notifications`, so it works on Plasma, GNOME and anywhere else
implementing the spec. Repeated switches replace one notification rather than
stacking. On a machine with no notification daemon the switch still happens, it
is just silent.

`linghub tray` puts an icon in the system tray with the active profile, a menu
to load any profile, and an entry to open the UI.

The tray is a **separate process**, and has to be: `AppIndicator3` is GTK3, and
GTK3 cannot be loaded in the same process as the GTK4 UI — `gi` refuses two
versions of the `Gtk` namespace. A separate process also means the tray survives
closing the window, which is the point of having one. It talks only to the
daemon, and "Open LinGHub" starts the UI as a subprocess.

Note that if you already run [Solaar](https://github.com/pwr-Solaar/Solaar) it
has its own tray icon for Logitech hardware, including battery reporting that
ratbagd does not expose. Two icons for one mouse is clutter; the LinGHub tray is
worth it only if you want click-to-open and profile switching from the tray.

## Running as a service

```bash
./scripts/install-service.sh     # install and start the user service
./scripts/uninstall-service.sh   # stop and remove it
```

The install script also offers to install `linghub-tray.service`, which puts the
tray icon in the session. It is a prompt rather than an assumption because the
tray needs a graphical session and a StatusNotifier host, and a headless machine
has neither. Set `LINGHUB_TRAY=yes` or `LINGHUB_TRAY=no` to skip the prompt.

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

## Versions and releases

The daemon, the tray and the window are separate processes, and each runs the
code that was on disk when it started. After a `git pull`, a daemon that hasn't
been restarted is still running the old code. Check with:

```console
$ linghub --version
LinGHub 0.1.0+3.g5c27eef
Daemon  0.1.0+3.g5c27eef
```

A third line appears when the two differ, such as `Daemon is running 0.1.0;
restart it`. A daemon too old to report its version shows `Daemon predates
version reporting; restart it`. If the daemon is running but its version
cannot be read, the line says `Daemon  unreadable` and no note is added: we
do not know that it differs. To restart both services:

```bash
systemctl --user restart linghub.service linghub-tray.service
```

The tray's last menu line and the window's About dialog show the same version,
and say the same thing when the daemon differs.

The version comes from git, read when each process starts:

| Version | Meaning |
| --- | --- |
| `0.1.0` | exactly the `v0.1.0` release |
| `0.1.0+3.g5c27eef` | 3 commits past `v0.1.0`, at commit `5c27eef` |
| `0.1.0+3.g5c27eef.dirty` | the same, with uncommitted changes |
| `0.0.0+66.gfb886ac` | no release tagged yet |

To cut a release, tag `main`:

```bash
git switch main && git pull
git tag v0.2.0
git push origin v0.2.0
```

Tag after a branch is merged, not on the branch itself: if the merge squashes
or rebases it, a tag made on the branch points at a commit `main` never
contains. Nothing needs bumping by hand; the version is the tag. See
[ADR-0009](docs/adr/0009-app-version-from-git-at-runtime.md) for why.

## D-Bus interface

The daemon publishes `org.linghub.Manager` on the session bus at
`/org/linghub/Manager`, so a UI can read state and request changes without
editing the config file.

| Member | Kind | Meaning |
| --- | --- | --- |
| `ListProfiles` | method → `as` | Every profile name in the config |
| `LoadProfile(s)` | method → `b` | Load a profile now; false if it does not exist |
| `Reload` | method → `b` | Re-read the config file |
| `GetView(s)` | method → `(sssasa(iss)a(us(uuu)uu)a(uuuu)auu)` | Everything a client shows, in one read: active profile, detected game, desktop profile, profile names; then the named profile's bindings (index, type, value), LED zones (index, mode, colour, brightness, duration), DPI slots (index, dpi, is_default, is_disabled), accepted report rates, and its current report rate. Unknown profile: empty sections |
| `SetBinding(s,i,s,s)` → `siss` | method → `b` | Assign one button's binding |
| `ClearBinding(s,i)` → `si` | method → `b` | Record a button as doing nothing |
| `SetLeds(s,s,u,u,u,u,u)` → `ssuuuuu` | method → `b` | Set every LED zone to one effect |
| `SetResolution(s,i,u,b,b)` → `siubb` | method → `b` | Change one DPI slot |
| `SetReportRate(s,u)` | method → `b` | Change the report rate |
| `CreateProfile(s,s)` | method → `b` | Add a profile; second argument is a game executable or empty |
| `RenameProfile(s,s)` | method → `b` | Rename a profile and every reference to it |
| `DeleteProfile(s)` | method → `b` | Remove a profile; refused for the desktop one |
| `ActiveProfile` | property `s` | Profile currently on the mouse, empty if unknown |
| `DetectedGame` | property `s` | Game currently detected, empty if none |
| `DesktopProfile` | property `s` | Profile used when no game is running |
| `Version` | property `s` | The daemon's app version: the code it loaded when it started (see ADR-0009) |
| `ProfileChanged(s)` | signal | A profile was loaded onto the mouse |
| `GameDetected(s)` | signal | A game started being detected |
| `GameExited(s)` | signal | A detected game stopped running |
| `ConfigChanged()` | signal | The config changed: an edit through this interface, or the file reloaded after a hand edit |

Every change a client shows is announced by one of these signals, so clients
re-read with `GetView` when a signal arrives rather than polling.

A manual `LoadProfile` is honoured whether or not a game is running. It lasts
until the current game changes, meaning a game starts or stops, and then
detection takes over again. With several games running, the current game is
the one started most recently, and that is the one `DetectedGame` reports.

```bash
busctl --user call org.linghub.Manager /org/linghub/Manager \
  org.linghub.Manager ListProfiles
```

## Configuration

The daemon reads `~/.config/linghub/config.json`. See
[config.example.json](config.example.json) for the shape. One file holds every
profile plus application settings (ADR-0004). The daemon is its only writer: the
UI edits over D-Bus and hand edits are picked up by watching the file.

Keys the daemon does not model are preserved when it writes, so a hand-written
comment or an extra field survives an edit from the UI. A config that fails to
validate is never written over.

## Documentation

- [Button map](docs/button-map.md) — manual number, G-name and ratbag index for
  every button, plus the supported variants
- [Glossary](GLOSSARY.md) — the vocabulary this project uses
- [Architecture decisions](docs/adr/) — why the design is the way it is
- [Architecture reviews](docs/reviews/) — deepening opportunities, dated

## Where the code lives

```
src/linghub/
├── domain/          Profile, Game, Binding — pure, no I/O
├── hardware/        ratbagd: reading, encoding, writing and verifying
│   ├── mouse.py     the mouse as the daemon sees it: connect, write, verify, read the slot
│   ├── failures.py  what can go wrong, in the daemon's terms: absent, lost, refused…
│   ├── hidpp.py     asks the mouse itself which slot it is on (ADR-0010)
│   └── active_slot.py    the mouse's answer over ratbagd's, and what a failed read means
├── discovery/       /proc and GameMode: is a game running?
├── daemon/
│   ├── service.py   the run loop; detection and the mouse are injected
│   ├── absence.py   one absence of the mouse, and what to say about it
│   ├── state.py     which profile should be on the mouse, and why
│   ├── writes.py    every config change, and the rule that persists it
│   ├── slots.py     which slot a profile belongs in (ADR-0001)
│   ├── collaborators.py  what the D-Bus adapter needs from the daemon
│   ├── dbus_service.py   the D-Bus surface itself
│   └── snapshot.py  the one read a client makes: state plus a profile
├── ui/
│   ├── window.py    the main window
│   ├── presentation.py   what the window should show, decided without a widget
│   ├── panel_rules.py    the DPI and lighting rules, without a widget
│   ├── binding_modes.py  how the editor's modes map to stored bindings
│   └── *_panel.py   widget wiring only
├── dbus_contract.py  one owner for member names and signatures
└── daemon_access.py  the shared entry point for CLI and tray
```

The pattern throughout: a decision that does not need a framework lives in a
module the framework calls, so it can be tested directly. `presentation`,
`panel_rules`, `binding_modes`, `slots`, `writes` and `active_slot` are all
that shape.

The daemon itself is tested the same way: it takes its detector and its mouse
connection as constructor arguments, so `tests/test_daemon.py` drives it one
`tick()` at a time against a fake mouse that can vanish, refuse a write, or be
moved to another slot. In production the mouse is `RatbagConnector`.

## Development

```bash
.venv/bin/python -m unittest discover -s tests -t .
```
