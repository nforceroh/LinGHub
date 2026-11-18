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

**Load**:
Writing a profile's contents into a slot and committing it to the mouse.
_Avoid_: push, apply, upload, sync

**Desktop profile**:
The profile loaded into slot 0, active whenever no game is running.
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
