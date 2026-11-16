# A single key can be sent two ways, and games differ on which they honour

A button that should send one key can be encoded as either `ACTION_KEY` with a
keycode, or `ACTION_MACRO` with a single press/release pair. They are not
interchangeable: they take different paths through the mouse's firmware, and
some games only respond to one of them.

World of Tanks under Wine ignores `ACTION_KEY` entirely and works with the
macro form. That was found empirically, not from documentation.

## Decision

Both are offered in the binding editor, as separate modes: "A single key" and
"A single key, as a macro". The config records which was chosen, and the editor
opens an existing binding in the mode that matches its stored type, so
re-saving cannot silently change the mechanism.

## Considered Options

- **Always use `ACTION_MACRO`** — works for the games tested, but a macro is a
  replayed sequence rather than a key event, which is heavier and may behave
  differently for games that do honour `ACTION_KEY`. It also makes the common
  case harder to read in the config.
- **Always use `ACTION_KEY`** — simpler, and correct for most games, but breaks
  World of Tanks, which is one of the two games this project was built for.
- **Detect the game and choose** — would need a per-game table of which
  mechanism each honours, which is unknowable in general and would be wrong for
  the next game.

## Consequences

- The binding editor has six modes rather than five, and two of them differ
  only in mechanism. The labels have to make that distinction legible.
- A binding's *type* is load-bearing: `key` and `macro` with the same value are
  different bindings, and verification compares the type as well as the value.
- When a config and the hardware disagree about the mechanism, the hardware is
  not necessarily stale. It may be the working configuration, and the config
  the thing that drifted.
