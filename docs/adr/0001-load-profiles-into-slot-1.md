# Load per-game profiles into slot 1 rather than pinning them to slots

The mouse has five profile slots, but slots 2–4 are disabled and empty, leaving
slot 0 for the desktop profile and slot 1 as the only usable gaming slot. We
therefore keep per-game profiles on disk and load the matching one into slot 1
when a game is detected, instead of pinning each game to its own slot.

Measured on the G502: a profile switch and a full profile write both cost about
0.6 s, because `Commit()` cost is fixed and independent of payload. Pinning
profiles to slots would therefore save nothing, while capping the number of
games at the number of free slots.

## Consequences

- The mouse keeps working with the daemon stopped: whatever was last loaded into
  slot 1 stays active.
- Every game start costs one commit (~0.6 s) and one flash write.
- Adding a game needs no slot management, only a new profile file.
