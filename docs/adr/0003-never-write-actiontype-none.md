# Never write ActionType NONE to a button

libratbag issue #1898 reports that writing `ActionType NONE` to a G502 Hero
button stores a corrupt macro binding instead of a no-op, leaving the button
showing as `macro 'None'`. The fix is proposed upstream but not merged. We
therefore never write NONE; an unassigned button is expressed as a harmless
Special action instead.

This is a deliberate deviation from the obvious implementation. A future reader
will see that "unassign" does not write NONE and may be tempted to simplify it.
Don't: the workaround is harmless on every device, and the bug's blast radius on
affected firmware is unknown.

## Consequences

- An unassigned button still emits something, so bindings must be chosen to be
  inert rather than absent.
- If upstream fixes #1898, this can be revisited, but there is no benefit to
  doing so.
