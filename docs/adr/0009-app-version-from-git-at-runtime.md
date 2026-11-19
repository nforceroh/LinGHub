# The app version is read from git when a process starts

LinGHub runs from a clone through an editable install, and its three processes
(daemon, tray, window) each load the code when they start. A number bumped by
hand would read the same across every commit between two releases, so it could
not answer the question that matters here: is this process running the code I
just pulled? A daemon left running on old code is the mismatch that actually
bites, and it is invisible otherwise.

## Decision

Git tags (`vX.Y.Z`) are the only source of the release number. Each process
runs `git describe` against its own clone at startup and formats the result as
`0.1.0` on a tag, `0.1.0+3.g5c27eef` past one, and adds `.dirty` when the
working tree has uncommitted changes. With no tag yet, the number is `0.0.0`.
When there is no clone to read, as in a future packaged install, the version
baked in at build time by `setuptools-scm` is used instead.

The daemon reports its version through a `Version` property on
`org.linghub.Manager`. The tray, the window and `linghub --version` each show
their own app version and the daemon's, and say so when the two differ.

## Considered Options

- **A version bumped by hand in one file** — simple, but it goes stale between
  releases, which is all the time when running from a clone, and the file and
  the tags can disagree.
- **`setuptools-scm` alone** — computes the right string, but an editable
  install records it once, at `pip install -e`, so it goes stale after the
  next commit for the same reason.
- **The daemon's version as a field of `GetView`** — one call instead of two,
  but changing that call's signature means a new window cannot unpack an old
  daemon's reply, so the whole window breaks in exactly the situation version
  reporting exists to diagnose. A separate property degrades to "this daemon
  predates version reporting" instead.

## Consequences

- Cutting a release is `git tag vX.Y.Z` on `main`. A tag made on a branch that
  is later squashed or rebased points at a commit `main` never contains.
- Two processes started from the same commit with different uncommitted edits
  both read `...dirty` and compare equal. Git cannot tell them apart, and only
  a developer's working tree is ever dirty.
- Startup runs one `git` subprocess. If git is missing or the clone is
  unreadable, the build-time version is used rather than failing.
