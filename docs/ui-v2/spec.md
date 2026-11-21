# UI version 2 — specification

Status: **draft, in grilling.** Sections marked *Settled* have been decided and
can be built. Sections marked *Open* are questions not yet asked or not yet
answered; nothing in them should be implemented.

This document is the record of the design conversation, not a plan of record.
When a section settles, it moves up and stops changing. When the whole document
settles, it becomes the input to an ADR if any decision in it is hard to reverse.

Vocabulary follows [GLOSSARY.md](../../GLOSSARY.md). Where this document and the
glossary disagree, the glossary wins and this document is wrong.

---

## 1. Why a version 2

The current window grew by accretion: a diagram pane, a profile list, a bindings
table, a DPI panel and a lighting panel, each added when it was needed. The
result is a window that does not fit on a 1366×768 laptop, a right column that
squeezes its own controls, and a DPI panel that spends a row per value on what
is really a position on a scale.

Version 2 is a layout and interaction redesign, not a rewrite. The daemon, the
config format, the D-Bus contract and the hardware layer are out of scope and
must not change.

---

## 2. Settled

### 2.1 Layout

*Settled in the 2026-11-21 grilling.*

- The mouse diagram and the profile list with its bindings share the **top
  row**, split by a horizontal `Gtk.Paned`.
- The DPI track and the lighting panel **span the full width** beneath them,
  rather than sitting inside the right column. They are wide controls, and the
  right column alone squeezed them while the diagram left a tall empty area
  beside them.
- The diagram is **top-aligned** in its pane. It cannot grow to fill a tall pane
  without distorting, so the space it leaves belongs at the bottom.
- The right pane is a **plain vertical box**, not a `Gtk.Paned`. The sections
  have natural heights and nothing needs to stretch, so a draggable divider
  would only let the user drag one into a useless position.
- The right pane **scrolls as one**. A `ScrolledWindow` per section reported a
  tiny natural height and clipped the bindings table to two rows.
- The window opens at **1140×840**, clamped to the monitor, and shrinks itself
  if the desktop restores a remembered size that no longer fits. A window taller
  than the screen hides its own bottom row.
- The lighting panel is a **2×2 grid**, not four stacked rows, because four rows
  made it the tallest thing in the window.

### 2.2 Section names and headings

- The `Buttons` section is renamed **`Bindings`**.
- The `DPI and report rate` heading is kept.
- The `Lighting` heading is kept.

### 2.3 Commit actions

- **Apply** and **Discard** replace the header-bar Save/Discard buttons.
- They sit at the **end of the Profiles header**, after `Load`, separated by a
  gap: the profile buttons choose *which* profile, these commit what you changed
  in it.
- They keep their icons (`document-save-symbolic`, `edit-undo-symbolic`) with
  tooltips, and stay disabled until something is pending.
- The per-panel `Revert` buttons are **removed**. Discard covers the whole
  profile, and the two per-panel buttons were redundant with it.

### 2.4 Status line

- The selected button is reported on the **status line**, not in a label under
  the diagram. It shares that line with the other transient messages.
- The detected game stays in the **header subtitle**.

### 2.5 The DPI track

*Settled in the 2026-11-21 grilling, questions Q1–Q17.*

The DPI panel is one track rather than a row per preset. Each preset is a
draggable marker on a shared scale.

**The scale**

- **Logarithmic**, because DPI is perceived proportionally: 400→800 is the same
  step as 1600→3200. A linear scale would spend most of its width above 10000,
  where nobody sets a DPI.
- Range 100–25600, the range ratbagd accepts for a G502.
- Dragging snaps to a **50 DPI step**, so a drag cannot produce 1237.
- Tick labels are **neutral and dim**. They are the scale, not presets;
  colouring them would imply they belong to a preset.

**The markers**

- A marker is a filled disc in its preset's colour.
- A **disabled** preset is a hollow ring in that preset's colour at reduced
  alpha. Shape and alpha carry the state; colour carries identity.
- The **default** preset is marked with an **underline in neutral white**. It is
  colour-independent, so colour carries preset identity and the underline
  carries default-ness, and the two signals never fight.
- Presets that share a DPI are **fanned out** side by side rather than drawn on
  top of each other, so each stays grabbable. Pinning every preset to one value
  is a legitimate setup; verified against ratbagd that five presets at 800 write
  and verify.

**The labels**

- Each label shows the DPI value, **coloured in the preset's colour**, with the
  **preset number as a superscript prefix** in the same colour — `⁴1600` reads
  as "preset 4 is at 1600".
- Presets that share a DPI share **one label**: the value in **neutral white**,
  with each preset's superscript number in its own colour — `¹²800`. The value
  belongs to the position; the numbers belong to the presets.
- Labels that would collide move up a row.

**The palette**

- Five colours, **indexed by preset number**, so preset 1 is always the same
  colour wherever it is dragged and across every profile. Sorting by value would
  recolour everything on every drag and the colour would stop identifying
  anything.
- The hues follow G HUB's (white, orange, teal, yellow, purple) but **vary
  lightness as well as hue**, so the markers stay distinguishable in greyscale
  and to colourblind users. Orange and yellow are the weak pair under
  deuteranopia; the printed number is the redundant signal that defuses it.
- Preset 1 is **white**, matching G HUB. The marker is a filled disc against an
  18%-alpha line, so the contrast is in the fill, not the hue.
- A fixed list of five. If a future mouse reports a different count the list
  cycles, but that is hypothetical and a fixed list keeps colours stable.

**The popover**

- Clicking a marker opens a popover with an exact DPI value, a `Default` tick
  and a `Disabled` tick. These are properties of a preset, not of the scale, so
  they cannot live on the track.
- The popover heading shows the preset number with a colour swatch, which is how
  a user learns that purple is preset 4.
- Ticking `Default` clears every other preset's default: ratbagd honours exactly
  one.

### 2.6 The profile selector

*Settled in the 2026-11-21 grilling, questions Q18–Q25.*

- The profile list in the main pane is **replaced** by a dropdown in the top
  right. Two places to choose a profile is the ambiguity the DPI panel grilling
  removed; the selector owns which profile the panels show.
- **Selecting from the dropdown loads that profile onto the mouse.** The
  select-versus-load distinction is gone: it was two actions on one list, which
  is the thing users are least likely to expect.
- **No categories.** A row shows the profile name alone, not `Category: Name`.
  Our model has no category, and inventing one would be a second place to keep
  a fact the config already holds.
- The active profile's row is **blue and carries a check**. Colour alone fails
  for colourblind users, and the check is already built.
- A **search field** filters the list, hidden below eight profiles. The dropdown
  is the only way to switch, so a long list would be painful without it.
- **`Manage profiles`** is pinned at the bottom and opens a **separate canvas**,
  not a dialog. See §2.7.

### 2.7 The manage-profiles canvas

*Settled in the 2026-11-21 grilling, question Q22.*

`Manage profiles` opens a canvas of its own, laid out like the reference: games
across the top, the selected game's profiles below. It is where profiles are
added, renamed and deleted, so the destructive actions and their confirmations
live away from the dropdown.

**A game carries a display name the user fills in.** The config stores an
executable (`WorldOfTanks.exe`); the canvas shows a name the user chose. This is
a new field on `Game` and a config format change.

### 2.8 Vocabulary

- The five DPI values are **DPI presets**, never "DPI slots". The bare word
  **Slot** always means a flash position a whole profile is loaded into.
  Recorded in [GLOSSARY.md](../../GLOSSARY.md).
- The rename reaches every **user-visible string and docstring**: the popover
  heading, the rejection message, the panel docstrings, the README.
- The config key `resolutions` and the D-Bus method `SetResolution` are **not**
  renamed. Neither is user-visible, both are load-bearing, and renaming them
  would be churn with a migration risk and no reader benefit.

---

## 3. Reference screenshots

Screenshots of the UI being aimed at live in [reference/](reference/). They are
reference, not specification: the goal is something similar, not a copy. Each
one is named for the screen it shows.

| File | Screen |
| --- | --- |
| [01-home-greeting.png](reference/01-home-greeting.png) | The home / greeting screen: a single device card centred on an empty canvas |
| [02-profile-selector.png](reference/02-profile-selector.png) | The profile selector dropdown, open |
| [03-manage-profiles.png](reference/03-manage-profiles.png) | The manage-profiles canvas: games across the top, profiles below |

### 3.1 What the home screen shows

*Observed from the reference, not yet decided.*

- A **device card** centred on an otherwise empty canvas. The card carries the
  device name, a battery indicator, the device image, and two icon buttons.
- A **profile selector** in the top right, showing the active profile as
  `Desktop: Desktop Main`.
- A **hamburger menu** in the top left.
- A **view toggle** in the top right of the canvas: a list icon and a grid icon.
- An **account icon** in the top right of the window.

### 3.2 What the profile selector shows

*Observed from the reference, not yet decided.*

- A **dropdown** in the top right, showing the active profile in the closed
  state as `Desktop: Desktop Main`.
- Open, it shows a **search field** ("Search profiles…"), then a **scrolling
  list** of profiles, then a **`MANAGE PROFILES`** action pinned at the bottom.
- Each row is a **document icon plus a `Category: Name` label**. The reference
  shows `Assetto Corsa: Default`, `Counter-Strike 2: Default`,
  `Desktop: Copy Paster`, `Desktop: Default`, `Desktop: Desktop Main`,
  `Valorant: Default`.
- The **active profile's label is blue**; the rest are white.
- The list **scrolls** — a scrollbar is visible on the right.

### 3.3 What the manage-profiles canvas shows

*Observed from the reference, not yet decided.*

- A **back arrow** in the top left, so the canvas is a place you navigate to
  and return from.
- A **`Games & Applications`** row of portrait tiles across the top, with an
  **`+ ADD GAME OR APPLICATION`** tile first. Tiles carry artwork; some read
  `NOT INSTALLED`. The selected tile is larger and labelled beneath
  (`DESKTOP`).
- A **tab bar** below: `PROFILES`, `MACROS`, `INTEGRATIONS`, `SETTINGS`, with
  the active tab underlined.
- A **profiles row** for the selected game, with an
  **`+ ADD PROFILE FOR THE SELECTED APP`** tile first, then one tile per
  profile showing its name and a blurred preview.
- Each profile tile has **`DETAILS`** plus three icon actions: a lighting icon,
  a share icon and a duplicate icon.

### 3.4 Facts verified for this screen

- **Battery is readable.** `/sys/class/power_supply/hidpp_battery_0/` reports
  `capacity` (95), `status` (Discharging) and `model_name`
  (`G502 LIGHTSPEED Wireless Gaming Mouse`). It is a kernel `hidpp_battery`
  device, so no HID++ work is needed. ratbagd does **not** expose battery, so
  this is a new read path.
- **The device is wireless.** It is a G502 LIGHTSPEED behind a PowerPlay
  receiver (`046d:c53a`), so a battery indicator is meaningful rather than
  decorative.
- **The reference device is not ours.** The screenshot shows a "G502 X PLUS",
  which is a different mouse. Our diagram is a G502 LIGHTSPEED.

---

## 4. Open

Nothing here is decided. Each item names the question, not an answer.

### 4.1 The bindings table

- The table has four columns (`Manual`, `Function`, `Does`, `Ratbag`). `Manual`
  exists only to help someone holding the printed manual, and `Ratbag` is the
  index the diagram labels. Is four columns the right shape for a compact
  window, or should the manual number fold into the function cell?
- Rows are click targets that open the binding editor. Is a row the right
  affordance, or should the `Does` cell be the only target so the row can carry
  other controls later?
- The table is not sortable and not filterable. With eleven rows that is fine.
  Does it stay fine?

### 4.2 The diagram

- The diagram is a static image with eleven hotspots. Should a hotspot show its
  current binding on hover, or is the table the only place bindings are read?
- The image is cropped to the mouse. Is there a use for the space beside it, or
  does it stay empty?

### 4.4 The lighting panel

- The G502 has two LED zones that read as one strip, so the panel drives them
  together. Should the zones be separately addressable?
- Effects are `off`, `fixed colour`, `cycle` and `breathing`. Is a dropdown the
  right control, or should the effect be a row of buttons?

### 4.5 The window as a whole

- Is there a compact mode, or a minimum size below which the layout reflows?
- Does the window need a keyboard-navigation story? Nothing is currently
  reachable without a pointer except the profile list.
- Should the window remember its own size and pane positions, given the desktop
  already remembers the size and that caused the too-tall-window bug?

### 4.6 Process

- Does version 2 ship as one change or as a sequence of independently shippable
  steps? The layout work already landed; the DPI track landed; the colour work
  has not.
- Does any decision here warrant an ADR? The candidates are the logarithmic
  scale (hard to reverse once users learn it, surprising without the
  proportional-perception reason) and the colour-indexed-by-preset rule (hard to
  reverse once users learn the palette).

---

## 5. What is already built

For orientation, so this document is not read as a plan for work already done.

| Piece | State |
| --- | --- |
| Two-row layout, full-width device panels | built |
| `Bindings` rename | built |
| Apply/Discard in the Profiles header | built |
| Per-panel `Revert` removed | built |
| Selected button on the status line | built |
| Window clamped to the monitor | built |
| Lighting as a 2×2 grid | built |
| DPI track, logarithmic, draggable, popover | built |
| Colliding markers fanned out | built |
| One label per distinct DPI | built |
| `DPI preset` in the glossary | built |
| Colour palette indexed by preset | **not built** |
| Superscript preset number on labels | **not built** |
| Neutral underline for the default | **not built** |
| `DPI preset` rename in user-visible strings | **not built** |
