# Put the DPI presets on a logarithmic scale

The DPI panel shows five presets on one track. The scale that maps a DPI value
to a position on that track has to be chosen, and the obvious choice — linear,
100 to 25600 in equal steps — is wrong for this control.

DPI is perceived proportionally. The step from 400 to 800 feels the same size as
1600 to 3200, because what a user notices is the ratio, not the difference. On a
linear scale those two steps are 400 and 1600 pixels apart: the first is
invisible and the second is a third of the track. Worse, a linear scale spends
about 90% of its width above 10000, where nobody sets a DPI. The five presets a
G502 actually ships with — 400, 800, 1000, and two disabled — would all crowd
into the first 4% of the track.

## Decision

The track's scale is logarithmic, from 100 to 25600. A preset's position is
`(log(dpi) - log(100)) / (log(25600) - log(100))`, inset from both ends so the
first and last markers are not clipped.

Dragging snaps to a 50 DPI step, so a drag cannot produce 1237. The exact value
is typed in the marker's popover, which is the only place a value that is not a
multiple of 50 can come from.

## Consequences

- Equal ratios are equal distances, so the track reads the way DPI is felt.
- The useful range — 100 to 6400 — occupies about 70% of the width instead of
  25%.
- The scale is not linear, so a marker's position cannot be read as a fraction
  of the range. Anything that needs the value must ask the preset, not the
  pixel.
- Tick labels are placed at fixed DPIs (100, 400, 800, 1600, 3200, 6400, 25600)
  rather than at even pixel intervals, because even pixel intervals would land
  on values nobody recognises.

## Alternatives considered

- **Linear, 100 to 25600.** Rejected: crowds every realistic DPI into the first
  quarter and wastes three quarters of the track on values nobody sets.
- **Linear, clamped to 100 to 6400.** Rejected: it hides the top of the range,
  so a preset above 6400 would have nowhere to sit.
- **A slider per preset, no shared scale.** Rejected: it was the design this
  replaced. Five rows of a number and a slider say nothing about where the
  presets sit relative to each other, which is the thing a user is choosing.
