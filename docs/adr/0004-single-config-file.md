# One config file holding all profiles plus application settings

Profiles and application settings live in a single file rather than one file per
profile. The file holds a `profiles` map keyed by profile name, plus a top-level
section for application settings that future features can extend without a
migration.

## Considered Options

- **One file per profile** — better for hand-editing and git diffs, but splits
  application settings away from the profiles they apply to and makes "which
  file is the desktop profile" a naming convention rather than a fact.
- **SQLite** — queryable, but opaque to hand-editing and to version control for
  a configuration file this small.

## Consequences

- The whole configuration is one atomic write, so there is no partially-applied
  state across files.
- Concurrent edits by hand and by the UI can conflict; the daemon is the single
  writer and the UI edits through it.
