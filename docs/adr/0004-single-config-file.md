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

## Amendment: a game carries a display name

A profile's `games` list used to hold bare executable strings:

```json
"games": ["WorldOfTanks.exe"]
```

The UI v2 manage-profiles canvas shows a game by a name the user chose, because
`WorldOfTanks.exe` is not what a user calls the game. A game entry therefore
gains an optional `name`:

```json
"games": [{"executable": "WorldOfTanks.exe", "name": "World of Tanks"}]
```

**The reader accepts both shapes.** A bare string is a game with no name, which
is what every config written before this change holds. The writer emits the
object form. This keeps the "no migration" property the original decision was
chosen for: an old config keeps working, and a new one is readable by an old
build only if it has no names — which is a narrower break than a version bump
and a migration step for a field that is purely cosmetic.

A nameless game is displayed as its executable with `.exe` stripped, so the
empty state is honest rather than invented.
