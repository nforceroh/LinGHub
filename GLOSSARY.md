# LinGHub

A Linux profile manager for the Logitech G502 family: it edits named profiles
and loads the right one into the mouse when a game starts.

## Language

**Profile**:
A named set of mouse settings — button bindings, DPI table, LED settings and
report rate — stored in the config and loaded into a slot when activated.
_Avoid_: preset, mode, layout

**Slot**:
One of the five numbered positions in the mouse's flash memory that a profile
can be loaded into, 0 through 4. Slot 0 holds the desktop profile; slot 1 holds
whichever gaming profile is active.
_Avoid_: index, bank, channel

**Device card**:
The picture of the mouse shown on the home screen. It identifies the hardware
and is the way into the configuration screen; it carries no hotspots, so it is
not a control for anything else. The card that holds it, its charge and its
buttons is the **home card**.
_Avoid_: diagram, product image, hero image

**DPI preset**:
One of the five DPI values a profile stores, each with a DPI, a flag for whether
it is the default, and a flag for whether it is disabled. Unrelated to a
**Slot**, which is a flash position a whole profile is loaded into: the bare
word "slot" always means the flash position, never a DPI value.
_Avoid_: DPI slot, resolution slot, DPI level

**Active slot**:
The slot the mouse is using right now, as the mouse itself reports it.
ratbagd's answer is only its belief about the active slot.
_Avoid_: current profile, selected slot

**Mouse**:
The connected G502 as the daemon sees it: found through ratbagd, its hidraw
node confirmed, then written to and read from. One module owns those
connection rules, so "is this the right device?" is answered in one place.
_Avoid_: device, hardware, writer

**Ratbagd miss**:
The kernel having a G502 that ratbagd has no device for, because ratbagd
enumerates once at startup and cannot rescan. Distinct from an absent mouse:
the mouse is there and the driver is unaware of it, so the cure is a udev
nudge rather than waiting. LinGHub tells them apart by scanning sysfs, and
only to choose which to report.
_Avoid_: stale device, desync, missing mouse

**Drift**:
The active slot differing from the slot the daemon last loaded a profile
into, whatever moved it: a profile button, a KVM switch, or another tool.
_Avoid_: desync, mismatch

**Load**:
Writing a profile's contents into a slot and committing it to the mouse.
_Avoid_: push, apply, upload, sync

**Refused load**:
A load the mouse or its driver would not accept, including one the mouse
itself denies: after the commit it is asked which slot is active, and an
answer other than the slot written refuses the load. It is not retried until
the profile, the config or the connection changes.
_Avoid_: failed write, rejected profile

**Desktop profile**:
The profile loaded into slot 0, active whenever no game is running. The daemon
assumes it is loaded before its first write, so clients show it rather than
"unknown" from the moment the daemon starts; the drift check corrects the
assumption if the mouse is elsewhere.
_Avoid_: default profile, base profile, normal profile

**Gaming profile**:
A profile intended to be active while a game is running. Profiles differ in
button bindings, DPI table and LED settings.
_Avoid_: game profile, play profile

**Binding**:
What a single mouse button does when pressed: a key, a modifier chord, a
special action, or nothing.
_Avoid_: mapping, assignment, action, shortcut

**Key binding**:
A binding that sends one key. It can be encoded two ways — as a key event, or
as a macro holding a single press/release pair — and some games only honour one
of them. See ADR-0008.
_Avoid_: keystroke, hotkey

**Special action**:
A mouse-internal behaviour such as DPI up/down or profile cycling, handled by
the mouse itself rather than emitted as a key.
_Avoid_: internal action, hardware action

**Second mode**:
The behaviour where a button temporarily changes what other buttons do. The
second-mode *action* is not supported by libratbag on the G502 and cannot be
assigned; the button that would trigger it remains fully bindable to any other
action.
_Avoid_: G-Shift, shift mode

**Game**:
A program that should cause the gaming profile to become active.
_Avoid_: application, title, process

**Game session**:
The interval during which a game is running, from detection to exit.
_Avoid_: game run, play session

**Detection**:
The act of deciding that a game has started or stopped.
_Avoid_: trigger, hook, watch

**Current game**:
The most recently started of the games running now. Its gaming profile is the
one detection chooses, and a different current game counts as the game
changing.
_Avoid_: detected game, active game, running game

**Manual override**:
A profile the user loads by hand, which replaces the profile detection would
choose. It holds whether or not a game is running, until a game starts or
stops, or another manual load replaces it.
_Avoid_: manual choice, pin, forced profile

**Commit**:
The asynchronous write of pending profile changes from the daemon to the
mouse's flash memory.
_Avoid_: save, flush, sync, apply

**Config**:
The single file holding every profile plus application settings. The daemon is
its only writer.
_Avoid_: settings, preferences, store, database

**Config format**:
The numbered layout of the config file, raised only when the file's structure
changes. Unrelated to the app version.
_Avoid_: config version, schema version

**App version**:
The build of LinGHub a running process loaded when it started: a release
number, plus how far past that release the code is. The daemon, tray and
window each have one, and they can differ until a stale process restarts.
_Avoid_: version (alone), build number, release

**Daemon version**:
What a client knows about the daemon's app version, as one of four values:
known, predates reporting, not running, or unreadable. The four are distinct
because they call for different words: only a known version can differ from
the client's own, and "unreadable" must never be shown as "not running".
_Avoid_: daemon state, version sentinel

**Config change**:
One edit to the config: a new binding, a DPI slot, a lighting effect, or a
whole profile. Every config change obeys the same rule — apply it, save it, and
undo it in memory if the save fails — so the file on disk and the running state
never disagree.
_Avoid_: write, mutation, update

**Collaborator**:
One of the three things the D-Bus adapter asks the daemon for: profile
lifecycle, bindings, or device settings. Grouping by what a method acts on
keeps the adapter's interface narrow and its implementations testable without
a bus.
_Avoid_: helper, handler, backend

**View**:
What the daemon publishes for a client to show, from one read: the state
section (active profile, detected game, desktop profile, profile names) and
one profile's editable sections. One read means a client cannot piece a view
together from two ticks.
_Avoid_: snapshot, DTO, payload

**Staged edit**:
An edit held in a panel until Save, so nothing reaches the mouse while the
user is still adjusting. The panel owns the widgets and the values; the
staged-edit module owns the baseline, whether the panel is dirty, and the
save/revert rule.
_Avoid_: draft, pending change, form state

**DPI track**:
The one-line scale in the DPI panel on which every slot is a draggable marker.
It shows all five slots at once, which a row per slot cannot, and it is the
only place a slot's position on the scale is visible. A slot's exact value,
whether it is the default, and whether it is disabled are properties of the
slot rather than of the scale, so they live in the marker's popover.
_Avoid_: slider, DPI bar, range widget

**Clone install**:
LinGHub run from a git clone through an editable install, where the app
version is read from git at startup (ADR-0009). Its service is
`linghub-dev.service`, so it never collides with a packaged install.
_Avoid_: dev install, development install, source install

**Packaged install**:
LinGHub installed from an RPM, where the app version is the one baked in at
build time. Its service is `linghub.service`, and it owns the desktop entry,
the icon and the AppStream metadata.
_Avoid_: production install, system install, release install

**Factory default**:
The config a fresh install starts with: one desktop profile holding the
G502's own settings. Written by `linghub init`, never by the daemon, and never
over an existing file.
_Avoid_: default config, starter config, template
