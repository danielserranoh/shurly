# Shurly design system

Brand, tokens and patterns behind the frontend. The living version, with every
component rendered from the real CSS, is **`/styleguide/`** in the app
(`frontend/src/pages/styleguide.astro`). Logo files and usage: [`brand/README.md`](brand/README.md).

## Personality

*Professional, with a wink.* Shurly talks like the Mac in the old "Get a Mac"
ads: relaxed, plain-spoken, a little dry, and never at the user's expense.

- Sentence case everywhere. Contractions are fine. No exclamation marks except "Copied!".
- Buttons are verbs that name the result: **Shorten**, **Add tags**, **Delete link**.
- Errors say what happened and what to do next, with no blame and no "Oops".
- One joke per screen at most, and never in an error or a destructive dialog.
  (The 404 gets one: "…And don't call us Shirley.")
- The UI says **link**. The API says URL. People say link.

## Tokens

All tokens live in `frontend/src/styles/global.css` (`@theme`, Tailwind 4) and are
available as utilities (`bg-ink-950`, `text-brand-700`, `rounded-xl`, `shadow-md`…).

**Colour.** Two scales do almost all the work.

| Scale | Use | Rules |
|---|---|---|
| `ink-50…950` (cool neutral) | text, surfaces, borders, primary buttons | `ink-500` is the lightest text shade: at least 4.5:1 on white, canvas and `ink-100`. `ink-400` is for icons and text on dark ink only |
| `brand-50…950` (Griddo blue) | the click dot, accent fills, links, charts, focus halo, success | `brand-400` `#5057ff` is the signature: white text on it (5.1:1), and fine as text on light (5.1:1 on white). Hover is `brand-500`. **On ink, use `brand-300`** for text and icons (10.6:1); `brand-400` on ink (3.9:1) only for large headlines |
| Surfaces | `canvas #faf9f6` page (warm off-white), `surface #fff` cards, `line` / `line-strong` borders | |
| Status | Tailwind `red` (error/danger), `amber` (warning), `blue` (info) | always paired with an icon and words |

**Type.** Logical, Griddo's typeface (`font-display`, the `.display` class), for page
titles and marketing headlines. Figtree (`font-sans`) for all UI text and numbers, with
tabular figures in tables. JetBrains Mono (`font-mono`, the `.shortlink` class) for short
links and codes. Figtree and JetBrains Mono are self-hosted (`@fontsource-variable/*`).
Logical is used when the browser has it and falls back to Figtree until its web font
files are added. The wordmark is Bricolage Grotesque, outlined in the SVG.

**Shape and depth.** Radius `sm 6 / md 8 / lg 10 / xl 14 / 2xl 18 / 3xl 24 px`:
inputs and buttons `lg`, cards `2xl`, dialogs `3xl`. Shadows `xs…xl`: cards sit
on `xs`, menus and popovers on `lg`, dialogs on `xl`. Spacing is Tailwind's 4 px grid.

**Motion.** `--ease-snappy` for UI, `--ease-spring` for small confirmations.
150–200 ms for hovers and presses, about 360 ms for entrances (`animate-fade-up`),
400 ms for the copy check (`animate-pop`). All motion is disabled under
`prefers-reduced-motion`.

## Components

CSS classes (in `global.css`): `btn` (+ `btn-primary | accent | secondary | ghost | danger | danger-ghost`,
`btn-sm | btn-lg | btn-icon`), `input` / `select` / `textarea` / `input-group`, `label`, `hint`,
`field-error`, `checkbox`, `switch`, `segmented`, `card` / `card-interactive`, `badge` (+ variants,
`badge-pro`), `tag[data-color]`, `status-dot`, `kbd`, `skeleton`, `spinner`, `table`, `menu`
(Popover API), `modal` (native `<dialog>`), `toast`, `disclosure`, `nav-link`, `tab`, `[data-tooltip]`.

Astro components (`frontend/src/components/`): `brand/Logo`, `ui/Icon` (Lucide), `ui/PageHeader`,
`ui/StatCard`, `ui/EmptyState`, `ui/Modal`, `ui/ProBadge`, `ui/PasswordField`,
`illustrations/Illustration` (11 line illustrations), `app/EditLinkModal`, `app/QrModal`.

Rendered in TypeScript (`frontend/src/utils/`): link card (`links.ts`), campaign card
(`campaigns.ts`), tag pill and tag picker (`tags.ts`, `tag-input.ts`), charts (`charts.ts`),
toasts, confirm dialogs and copy feedback (`ui.ts`). Every interpolation goes through the
escaping `html` template tag (`html.ts`).

## Patterns

- **Loading.** Skeletons shaped like the content for first loads. Later reloads dim the list
  in place. The spinner is a pinging brand-blue dot.
- **Empty.** Illustration, one sentence on what goes here, and the action that fills it.
  "No results" is a different state from "nothing yet" and offers a way to clear the filters.
- **Errors, by severity.** Field problems appear inline under the field (focus moves to the first one, and
  collapsed sections open). Form-level API errors go in an alert inside the form. Background or
  async failures show a toast. A page that fails to load gets an error state with **Try again**.
- **Destructive actions** use a confirm dialog that names the consequence ("…will stop working for everyone
  who has it") and a red, specific button ("Delete link").
- **Copy.** The button turns blue and reads "Copied!" for 2 s. A toast is added only when the button
  isn't where you're looking (auto-copy after quick create, bulk copy).
- **Toasts** appear top-right under the header: 4 s, or 6 s for errors.
- **Dialogs** fade and scale in and become bottom sheets under 640 px. **Menus** use the Popover API.
- **Keyboard.** `N` opens a new link and `/` focuses search. Every control has a visible focus ring
  (ink ring + blue halo).
- **Responsive.** Desktop-first, checked at 1440 and 390 px. Under `md` the nav moves into a menu dialog.

## Paywall

Plans follow the brief's Free/Pro split (§7, `frontend/src/config/site.ts`), but Pro is not on sale
yet (pricing reads "announced soon") and the API has no billing, so nothing is enforced. The rules:

1. Never lock something that works today. During early access every working feature is unlocked for
   everyone, including the ones the Plan tab lists under Pro (social preview editing, API & MCP).
2. Pro-only controls are visible but disabled, marked with a `ProBadge` or lock icon and a tooltip saying
   what Pro adds ("Longer ranges come with Pro"). Features that aren't built yet use `ProBadge label="Coming soon"`.
   Examples: analytics ranges beyond 7 days, QR brand colours and logo, click notifications.
3. The copy says "Unlock with Pro". It never says "Upgrade now!", and it never uses a blocking modal.

## Charts

One series in `brand-400`, Griddo blue (validated for contrast and colour-vision deficiency; hover `brand-600`). Bars are 24 px
or thinner with a 4 px rounded data end. Grid lines are hairlines. Only the maximum is
labelled, and every mark has a hover/focus tooltip. Each chart has a **Table** toggle
showing the same data. Stat numbers use the UI sans, not the display face.

## Decisions on the brief's open questions (§11)

| # | Question | Decision |
|---|---|---|
| 1 | Wordmark or symbol? | Both. The wordmark with the blue click dot is primary. The "s." isotype is for favicons, app icons and avatars. |
| 2 | Vibrant or sober? | Sober ink base, one vibrant accent. Griddo blue is rationed so it always means "this is the action / this worked". |
| 3 | Illustration style | Minimal line-art in ink with brand-blue accent fills, drawn as inline SVG (`Illustration.astro`). |
| 4 | Hero message | "Send the link. Know who opened it." It is concrete, fits B2B outreach, and campaigns follow from it. |
| 5 | Tag colours | A fixed colour per category for predefined tags (blue channel, green intent, purple content type, orange audience, pink lifecycle). Your own tags are neutral gray. No hash colours, so the colour always means something. |
| 6 | Link preview card | Live in Create (as you type), full on the link details page, and collapsed to a thumbnail on dashboard cards. |
| 7 | Last click time | Relative on screen ("3h ago"), absolute in the tooltip (`<time data-relative>`). |
| 8 | Copy feedback | The button changes state, plus a toast only when the button is off-focus (see Patterns). |
| 9 | OG auto-fetch | Both. It fetches automatically on paste or blur (debounced), and a manual **Fetch preview** / refresh is always available. |
| 10 | Error handling | A mix by severity: inline, then form alert, then toast, then error page. Confirm dialogs only for destructive actions. |

## Screens

Static routes, so `frontend/dist/` can be served from S3. Record pages take a query parameter
instead of a dynamic path.

`/` landing · `/login/` · `/register/` · `/404` · `/styleguide/` · `/dashboard/` links ·
`/dashboard/create/` · `/dashboard/link/?code=…` · `/dashboard/campaigns/` ·
`/dashboard/campaigns/create/` (4-step wizard) · `/dashboard/campaign/?id=…` ·
`/dashboard/analytics/` · `/dashboard/settings/` (`#account`, `#api`, `#tags`, `#notifications`, `#plan`).
