# English only, with no internationalisation layer

All user-facing text is written inline in English. There is no translation
catalogue, no `_()` wrapper, and no language preference.

The reference implementation this project borrows from carries a 187-line
translation table, a `_()` wrapper around every UI string, and a preferences
file to persist the chosen language. That machinery exists to support Spanish
and English. This project needs only English, so the indirection is removed
rather than kept as a no-op.

## Considered Options

- **Keep `_()` as a passthrough** — would leave roughly 200 pointless call sites
  in the code for a feature that was explicitly declined.
- **Keep the full catalogue, English only** — carries the maintenance cost of a
  translation table with nothing to translate.

## Consequences

- Adding a language later is a mechanical refactor: wrap the strings, extract
  them, add a catalogue. It is not a reason to carry the indirection now.
- Ported code from the reference implementation must be translated to English,
  including comments and docstrings, so the repository contains no mixed
  language.
