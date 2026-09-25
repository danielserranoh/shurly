# Shurly brand assets

The mark is the word **shurly** in custom rounded lettering, with a diamond for a
period: the *click*. Griddo navy carries the letters; the diamond is the one
accent, Griddo blue on light surfaces and cyan on navy.

![Logo](png/shurly-logo-horizontal@2x.png)

## Files

All SVGs are outlined paths (no live text) and derive from one master geometry, so
every colourway lines up exactly.

| Asset | SVG (source of truth) | PNG @1x/2x/3x |
|---|---|---|
| Logo, navy + blue diamond, for light surfaces | `svg/shurly-logo-horizontal.svg` | `png/shurly-logo-horizontal@*.png` |
| Logo, white + cyan diamond, for navy / dark | `svg/shurly-logo-horizontal-reversed.svg` | `png/shurly-logo-horizontal-reversed@*.png` |
| Logo, one colour | `svg/shurly-logo-horizontal-mono-navy.svg`, `svg/shurly-logo-horizontal-mono-white.svg` | `png/shurly-logo-horizontal-mono-*@*.png` |
| Isotype "sy", navy tile + cyan diamond, for light surfaces | `svg/shurly-isotype-reversed.svg` | `png/shurly-isotype-reversed@*.png` |
| Isotype "sy", white tile + blue diamond, for dark surfaces | `svg/shurly-isotype.svg` | `png/shurly-isotype@*.png` |
| Mark without tile | `svg/shurly-isomark.svg`, `svg/shurly-isomark-reversed.svg` | `png/shurly-isomark*@*.png` |
| Favicon pack (navy tile) | `svg/shurly-favicon.svg` | `png/shurly-favicon.ico`, `png/shurly-apple-touch-icon.png`, `png/shurly-android-chrome-512x512.png` |
| Social card (1200×630) | — | `png/shurly-og-image.png` |

The web app serves its own copies from `frontend/public/brand/` and
`frontend/public/` (favicons, manifest, `og-image.png`). In Astro, use
`components/brand/Logo.astro` (`variant="wordmark" | "isotype"`,
`tone="default" | "reversed" | "mono"`): `default` is for light surfaces,
`reversed` for dark ones.

## Construction

- Lettering: custom rounded strokes, 20-unit stem; the `y` descender takes about a
  quarter of the logo's height. Never re-type the name in live text.
- Diamond: a 22 × 22 square rotated 45° (31 units wide), after the `y` on the x-height baseline.
- Wordmark box: 463.11 × 176.45 (ratio 2.625), including the descender. Because the
  box includes it, set the logo about 1.35× taller than a cap-height logo
  (web header: 30 px).
- Isotype: "sy" plus the diamond on a 240 × 240 tile, corner radius 32 (13%).
- Clear space: one diamond width on every side. Minimum size: logo 20 px tall,
  isotype 16 px (favicon).

## Colour

| Role | Value |
|---|---|
| Letters, tile | Griddo navy `#001b3c` (white when reversed) |
| Diamond on light | Griddo blue `#5057ff` |
| Diamond on navy | Cyan `#3cc3dd` (token `brand-cyan`, logo only) |
| Paper | `#ffffff` / canvas `#faf9f6` |

## Don't

- Recolour the diamond: blue on light, cyan on navy, or the single colour of a mono version.
- Put the blue diamond on navy (3.4:1, it sinks) or the cyan one on white (2:1).
- Put the full-colour logo on brand blue; use mono white.
- Stretch, outline, add shadows, or place it on a busy photo. Use the reversed or mono versions.
