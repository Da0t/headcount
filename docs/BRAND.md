# Headcount brand

<img src="../app/static/logo.svg" width="280" alt="Headcount">

## Concept

A house holding a tally: four strokes and the fifth crossing them. Every person counted, every person home.
The mark is drawn by hand from simple geometry (a 64-unit grid, round caps and joins), so it stays bold down to 16px.

## Files (`app/static/`)

| File | Use |
|---|---|
| `logo.svg` | Mark and wordmark, full color, on light backgrounds |
| `logo-reversed.svg` | Mark and wordmark on dark backgrounds (white, orange stroke kept) |
| `logo-mono.svg` | One color, follows `currentColor` |
| `logo-mark.svg` | Mark only, square, full color |
| `logo-mark-mono.svg` | Mark only, one color, follows `currentColor` |
| `favicon.svg` | Browser tab icon: white house on an orange rounded square, built for 16 to 32px |

The wordmark is live `<text>` (Inter, then the system sans), with "count" in orange.

## Colors

| Name | Hex | Use |
|---|---|---|
| Headcount orange | `#F26B1D` | The crossing stroke, "count", the favicon background |
| Ink | `#1A1A1A` | House, tally strokes, "Head" |
| White | `#FFFFFF` | Reversed logo, favicon house |

The dispatch board tunes its orange per theme for contrast (`#ff9a3c` on dark, `#c2570c` on light). Use those inside the board UI and `#F26B1D` for the logo.

## Clear space and size

- Keep clear space around the logo at least the height of the house's roof (one quarter of the mark's height) on every side.
- Minimum size: the mark at 20px, or the full logo at 120px wide. Below 20px, use `favicon.svg`.

## Do

- Use the reversed logo on dark backgrounds and the mono logo when only one color is available.
- Keep the crossing stroke orange whenever color is available. It is the "everyone accounted for" moment.

## Don't

- Don't stretch, rotate, outline or add shadows to the mark.
- Don't change the number of tally strokes or move the crossing stroke outside the house.
- Don't recolor it to look like a government or emergency-agency seal. Headcount is not an official alert system.
