# Read the active slot from the mouse; write through ratbagd

Until now LinGHub reached the hardware only through ratbagd. But ratbagd
answers "which profile is active" from what it has cached, and on 2026-11-19
that answer was wrong three times: slot 1 while the mouse sat on slot 0 (in
game it behaved like the desktop profile), then the disabled slot 2 after
each of two KVM switches. libratbag also has no handler for the onboard
profiles feature's events, so a press of the mouse's profile button never
reaches it. The daemon's drift check rested on that answer, so drift could
go unnoticed and uncorrected.

## Decision

The daemon asks the mouse which slot it is on, over HID++ 2.0 (onboard
profiles feature `0x8100`: `getOnboardMode`, then `getCurrentProfile`), on
every check. When ratbagd disagrees, the mouse wins. All writes still go
through ratbagd. LinGHub only reads the mouse directly.

A load is confirmed the same way: after the commit, the daemon asks the mouse
which slot is active and refuses the load if the answer is not the slot it
wrote. ratbagd's `IsActive` is not trusted for this, for the same reason its
active-slot answer is not: it is ratbagd's belief, and it has been wrong. A
mouse that cannot answer does not fail the load — the write itself was
verified, and the next drift check asks again.

- **The node** comes from the ratbagd device the daemon has just confirmed
  (`.../device/hidrawN` → `/dev/hidrawN`). It is checked against sysfs to be
  a Logitech device, and if it isn't, the daemon uses ratbagd's answer for
  that connection and logs an error once. If the node is missing from sysfs
  altogether, the mouse is gone and the connection fails: ratbagd lags the
  kernel by about 2 s after a KVM switch, so for a moment it still lists a
  mouse whose node no longer exists.
- **The node is opened for each read** and closed straight after, so a node
  deleted by a KVM switch is never held open.
- **Sharing:** ratbagd (software id `0x8`) and the kernel (`0x1`) use the same
  node, and every reader sees every reply. LinGHub uses `0xA` and ignores
  replies that are not answers to its own request. There is no locking.
- **Addresses:** the wired address (`0xFF`) is tried first, then the
  receiver's (`0x01`). Whichever answers is kept for the connection.

A failed read means different things, and only one of them is a lost mouse:

| What happened | Meaning | Daemon |
| --- | --- | --- |
| The node is gone | the mouse is lost | reconnect |
| No reply in time, or a HID++ error | slot unknown | nothing; ask again next check |
| Permission denied (another session has the seat) | use ratbagd's answer | one warning |
| The mouse is in host mode | slot unknown | one warning |

## Considered Options

- **Keep trusting ratbagd.** No second path to the hardware, but the drift
  check is blind exactly when it matters: after a KVM switch, and after a
  profile-button press.
- **Read the mouse only after reconnecting or loading.** Less wireless
  traffic, but a profile-button press would still go unnoticed. Two short
  requests every two seconds cost about 20 ms.
- **Find the node by scanning sysfs for a G502 USB id.** Doesn't depend on
  ratbagd's naming, but needs a list of every G502 model's id. ratbagd has
  already identified the device, so the daemon reuses that and checks it.
- **Treat any failed read as a lost mouse.** Simpler, but a sleeping mouse
  would make the daemon reconnect every two seconds.

## Consequences

- LinGHub now has two paths to the hardware: reads over HID++, writes through
  ratbagd. A mouse without feature `0x8100` would leave the slot unknown on
  every check, which disables drift correction for it.
- The first read on each connection costs up to the reply timeout (about
  0.5 s) when the mouse is behind a receiver, because the wired address is
  tried first and the receiver doesn't answer it. It runs off the event loop.
- `ratbagctl` can still show a different active profile than the mouse. The
  daemon logs each disagreement once, which keeps a record of ratbagd's wrong
  answers.

## Amendment: reading sysfs when ratbagd finds no mouse

On 2026-11-20 the daemon spent 50 minutes reporting the mouse absent while it
was connected and working. ratbagd had started at 08:42:06 and the G502's
HID++ stack came up at 08:43:02; ratbagd enumerates hidraw nodes once at
startup (its initial scan skips nodes udev has not finished initializing) and
does not rescan. A mouse that initializes late is
therefore never added, and no number of retries helps: `Manager.Devices` has
no rescan method in any released version. A udev `add` for the node does make
ratbagd pick it up.

The original decision found the node *from* a ratbagd device, which cannot
detect this case, because there is no ratbagd device to start from. The rule
is therefore extended by the smallest amount that answers "is the mouse there
at all?": when ratbagd reports no G502, LinGHub scans sysfs itself and looks
for a hidraw node the kernel names as a Logitech G502.

This does **not** weaken the decision that writes go through ratbagd:

- The scan never chooses a device to write to. It only decides which of two
  failures to report.
- A node found this way is never used to read the active slot either: without
  a ratbagd device there is nothing to load a profile into, so the slot is
  moot.
- The result is a `MouseMisconfigured` naming the fix (a udev remove/add for
  that node), not a connection. The mouse stays absent until ratbagd sees it,
  so the existing retry loop is untouched.

The alternative — auto-restarting ratbagd — was rejected for now: it needs
either a root helper or a polkit rule in the package, and it would hide an
upstream bug rather than surface it.
