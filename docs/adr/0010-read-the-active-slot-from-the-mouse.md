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
