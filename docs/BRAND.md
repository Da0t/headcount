# Headcount brand

<img src="../app/static/logo.svg" width="280" alt="Headcount">

## Concept

A house holding a tally: four strokes and the fifth crossing them. Every person counted, every person home.
The mark is drawn by hand from simple geometry on a 64-unit grid: a white house on a solid orange rounded tile, so it stays bold down to 16px.

## Files (`app/static/`)

| File | Use |
|---|---|
| `logo.svg` | Tile mark and wordmark, full color, on light backgrounds |
| `logo-reversed.svg` | Tile mark and wordmark on dark backgrounds (white "Head", lighter orange "count") |
| `logo-mono.svg` | Tile mark and wordmark in one color, follows `currentColor` (the house is knocked out of the tile) |
| `logo-mark.svg` | Tile mark only, square, full color |
| `logo-mark-mono.svg` | Tile mark only, one color, follows `currentColor` (the house is knocked out of the tile) |
| `favicon.svg` | Browser tab icon, the same tile mark, built for 16 to 32px |

The wordmark is live `<text>` (Inter, then the system sans): "Head" in ink and "count" in orange.

## Colors

| Name | Hex | Use |
|---|---|---|
| Headcount orange | `#C2410C` | The tile, the four tally strokes, "count" on light backgrounds |
| Light orange | `#FB923C` | "count" on dark backgrounds (reversed logo) |
| Ink | `#1C1D21` | The crossing stroke, "Head" on light backgrounds |
| White | `#FFFFFF` | The house, "Head" on dark backgrounds |

The board's accent color is the same `#C2410C`, so the logo and the UI match.

## Clear space and size

- Keep clear space around the logo at least the height of the house's roof (one quarter of the mark's height) on every side.
- Minimum size: the mark at 20px, or the full logo at 120px wide. Below 20px, use `favicon.svg`.

## Do

- Use the reversed logo on dark backgrounds and the mono logo when only one color is available.
- Keep the crossing stroke in ink, across the orange tallies. It is the "everyone accounted for" moment.

## Don't

- Don't stretch, rotate, outline or add shadows to the mark.
- Don't change the number of tally strokes, move the crossing stroke outside the house, or drop the house onto a background without its tile.
- Don't recolor it to look like a government or emergency-agency seal. Headcount is not an official alert system.
