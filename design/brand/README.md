# Shurly brand assets

The mark is the word **shurly** with a lime period: the *click dot*. A link
someone opened, rendered as a full stop. Everything else in the identity is
quiet ink, so the dot is the one thing you remember.

![Horizontal lockup](png/logo-horizontal@2x.png)

## Files

| Asset | SVG (source of truth) | PNG @1x/2x/3x |
|---|---|---|
| Wordmark, ink on light | `svg/wordmark.svg` | `png/wordmark@*.png` |
| Wordmark, white on dark | `svg/wordmark-reversed.svg` | `png/wordmark-reversed@*.png` |
| Wordmark, one colour | `svg/wordmark-mono-ink.svg`, `svg/wordmark-mono-white.svg` | — |
| Isotype "s." (ink tile) | `svg/isotype.svg` | `png/isotype@*.png` |
| Isotype, lime tile / one colour | `svg/isotype-lime.svg`, `svg/isotype-mono-ink.svg`, `svg/isotype-mono-white.svg` | — |
| Horizontal lockup | `svg/logo-horizontal.svg`, `svg/logo-horizontal-reversed.svg` | `png/logo-horizontal*@*.png` |
| Vertical lockup | `svg/logo-vertical.svg`, `svg/logo-vertical-reversed.svg` | `png/logo-vertical@*.png` |
| Favicon pack | `svg/favicon.svg` | `png/favicon.ico`, `png/apple-touch-icon.png`, `png/android-chrome-512x512.png` |
| Social card (1200×630) | — | `png/og-image.png` |

The web app serves its own copies from `frontend/public/` (favicons, manifest,
`og-image.png`) and `frontend/public/brand/`. In Astro, use
`components/brand/Logo.astro` (`variant="wordmark" | "isotype"`,
`tone="default" | "reversed" | "mono"`).

## Construction

- Letters: Bricolage Grotesque ExtraBold (800), converted to outlines, tracking −40 units.
  Never re-type the wordmark in live text.
- Dot: brand lime `#b8f03e`, diameter 176 units (the stem is 158, so the dot reads
  slightly heavier than a letter), 16-unit gap after the `y`, sitting on the baseline
  with a 12-unit overshoot.
- Isotype: the same "s." centred in a 512 × 512 tile, corner radius 118 (23%).
- Clear space: one dot diameter on every side. Minimum size: wordmark 64 px wide,
  isotype 16 px (favicon).

## Colour

| Role | Value |
|---|---|
| Ink (text, tile) | `#090d13` |
| Click dot | `#b8f03e` |
| Paper | `#ffffff` / canvas `#f5f6f8` |

## Don't

- Recolour the dot (it is lime, or the single colour of a mono version).
- Use lime for the letters, or set lime text on a light background (1.3:1 contrast).
- Stretch, outline, add shadows, or place the full-colour wordmark on a busy photo.
  Use the reversed or mono versions instead.
