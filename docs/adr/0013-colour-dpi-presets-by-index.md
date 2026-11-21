# Colour a DPI preset by its index, not by its position

The DPI track draws five presets as coloured markers, and the colour is how a
user tells one preset from another. There are two ways to assign the colours,
and the more obvious one is wrong.

Assigning colour by **sorted position** — lowest DPI gets the first colour, next
gets the second — looks natural, because the track is ordered by value. But
dragging a preset past another would swap their colours. The colour would then
identify a *rank*, not a preset, and it would change every time the user moved
something. A user who learns "purple is my 3200 preset" would find purple on a
different preset after one drag.

## Decision

Colour is assigned by **preset index**: preset 1 is always the first colour,
preset 2 the second, and so on, wherever they sit on the track and whichever
profile is being edited.

The palette is five colours, indexed by preset number, following G HUB's hues
(white, orange, teal, yellow, purple) but varying lightness as well as hue so the
markers stay distinguishable in greyscale and to colourblind users. Orange and
yellow are the weak pair under deuteranopia; the printed DPI value beside each
marker is the redundant signal that defuses it.

Colour is never the only signal. The default preset is marked with a neutral
underline, a disabled preset is a hollow ring, and every marker carries its
value and its preset number.

## Consequences

- A preset's colour is stable across drags, across profiles and across restarts.
- The colour carries no information about the value, so two presets at the same
  DPI are still distinguishable — which is the case the fan-out exists for.
- The palette is a fixed list of five. A mouse reporting a different preset
  count would cycle the list; no such mouse is supported.
- Colour is redundant encoding, not the primary one, so the palette does not
  have to carry the whole burden of accessibility.

## Alternatives considered

- **Colour by sorted position.** Rejected: the colour would stop identifying
  anything the moment a preset moved.
- **Colour by DPI value** (a gradient along the scale). Rejected: it encodes the
  value, which the position already encodes, and leaves presets at the same DPI
  indistinguishable.
- **No colour, numbers only.** Rejected: it is what the track had before, and
  five markers 14px apart with only a number each is hard to scan.
