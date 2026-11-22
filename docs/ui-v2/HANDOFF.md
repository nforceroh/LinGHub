# ui-v2 handoff — 2026-11-21

Everything needed to continue lives in the repo. This file is the map; the
branch is `ui-v2`, pushed to `origin`, tip `b88e705`.

## Where things stand

The UI v2 redesign is mid-build on branch `ui-v2`. Built and committed:

- **Game display name** (step 1, `853719f`): `Game` carries an optional
  `name`; config reader accepts bare-string and object forms, writer emits
  the object form; ADR-0004 amendment.
- **Profile selector** (step 2, `3221fae`): dropdown in the header's top
  right; choosing loads onto the mouse; Manage opens the canvas.
- **Home screen** (`b9ebc08`…`947fda3`): device card, battery read from
  sysfs, back arrow.
- **Manage-profiles canvas** (step 5, `4ef4b09` + `58e16a7`): games row and
  profiles row as views inside the main window; ADD GAME (editable path +
  Browse + display name + profile), edit-game (rename display name, no
  profile field), duplicate, delete, DETAILS (edits without loading),
  back arrow, pending-edits prompt. Daemon gained `DuplicateProfile`,
  `RenameGame`, and GetView summaries (`name, default DPI, report rate,
  games as (executable, display name)`).
- Spec table of what is built: `docs/ui-v2/spec.md` §5.

Tests: **893 passed, 1 skipped** (` .venv/bin/python -m pytest tests/`).

## Not built yet (build order §2.13)

3. **Navigation restructure** — partially built. The configuration screen now
   has the DPI / Assignments / LIGHTSYNC icon rail and the Assignments sidebar.
   Leader lines and labels are present on the diagram. Remaining work:
   Default/Second mode, preset-colour polish, and the final LIGHTSYNC visual.
4. **Colour palette + preset numbers** (ADR-0013), self-contained.
- LIGHTSYNC view, onboard-memory screen (no spec section — see §4 Open),
  DPI legend row, Assignments labels with leader lines, Default/Second-mode
  toggle.

## Working rules that cost blood to learn

- **GTK single-instance gotcha**: a second process with app id
  `org.linghub.UI` hands over to the running window and kills it. Probes
  must set `LINGHUB_PROBE=1`, which switches the id to
  `org.linghub.UI.Probe`. Never full-screen-capture while the user games;
  verify by widget-tree probe or ask the user to look.
- **GetView returns two top-level structs**: the state+sections nine, then
  the summaries list. `_real_fn_result_to_body` counts a return's *top
  level*; the daemon returns a 2-tuple of structs, and the client's
  `_call` must return the whole body (it used to keep only `body[0]`, which
  silently dropped the summaries). A daemon too old to have summaries
  decodes to `()`; the canvas falls back to name-only tiles.
- **Summary struct signature is `(suua(ss))`** — name, dpi(u), rate(u),
  games array-of-(ss). Writing `(ssu(ss)s)` parses as five fields and the
  marshalling fails at reply time on the bus, but only against a *live*
  daemon: unit tests pass either way. When a D-Bus shape changes, restart
  the daemon and read it live before trusting the tests.
- **`make_window()` in tests/support.py must gain every new MainWindow
  field** — the window is built without `__init__`. The canvas widget is
  `_manage`, added to the stack as `"manage"`.
- **All async work goes through `self._schedule`**, not `run_and_report`
  directly, or tests cannot drive it. The one exception: a callback from a
  prompt that has already closed (rename-game) uses `run_and_report` and
  reports on the status line.
- **The dialog callback arity**: `AddGameDialog` calls
  `on_accept(executable, name, profile)` — three args, always, in both the
  add and edit flows (edit passes an empty profile).
- **User vocabulary**: the mouse picture is the **device card**; the card
  that holds it is the **home card**; the five DPI values are **DPI
  presets**, never slots. GLOSSARY.md wins over any doc.

## Session-level context (not in the repo)

- The user works across PCs; keep design artifacts in the repo (they are).
- Issues are tracked on GitHub (`docs/agents/issue-tracker.md`); labels per
  `docs/agents/triage-labels.md`.
- The daemon (`linghub-dev.service`) and tray (`linghub-dev-tray.service`)
  run as systemd user units from the clone. Restart the daemon after
  changing the D-Bus contract.
- Monitor: 2648×1490 at scale 2 (1324×745 logical).
