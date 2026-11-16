# Derive device capabilities from D-Bus, not from a static variant table

We identify a G502 variant by USB ID to get its display name, but every
capability — DPI range, LED zones, report rates, button action types, profile
count — is read from ratbagd at runtime rather than from a hardcoded table.

A static table was tried and found wrong. The reference implementation's table
claims 25600 DPI and a battery interface for the G502 Lightspeed (`046d:407f`);
the actual device reports a 25500 DPI ceiling and exposes no battery interface
through ratbagd 0.18. The same table omits the G502 X PLUS entirely and omits
one of the two USB IDs for the G502 X Wireless.

A table that is wrong for the developer's own mouse is worse than no table.

## Consequences

- Capabilities are discovered per device, so a libratbag update that adds
  support is picked up without a code change.
- The variant table still exists, but only maps USB ID to a display name.
- Features must degrade gracefully when a capability is absent, rather than
  assuming it from the model name.
