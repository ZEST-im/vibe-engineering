# ZEST UI — design language

> Source: `@zest-im/ui` → `src/styles/tokens.css`, read 2026-08-15.
> **Free to use.** The npm package is private, but the design language is not — everything
> needed to use it is in this file. Copy the tokens; you do not need the package.

## Character

Quiet surfaces, one loud accent. Cool grays instead of true black, borders that barely
exist, generous corner radii, shadows you notice only when they are gone. Depth comes
from a white card on a gray field — not from lines or heavy shadow.

The accent does a lot of work because almost nothing else is colored.

## Tokens

```css
:root {
  /* Surfaces — white cards on cool gray */
  --bg: #ffffff;  --bg-soft: #f7f8fa;  --bg-subtle: #f2f4f6;
  --bg-emphasis: #e5e8eb;  --bg-tertiary: #f9fafb;

  /* Text — soft cool gray, never pure black */
  --text: #191f28;  --text-secondary: #4e5968;
  --text-muted: #8b95a1;  --text-faint: #b0b8c1;

  /* Borders — nearly invisible */
  --border: #f2f4f6;  --border-soft: #f7f8fa;  --border-strong: #e5e8eb;

  /* Accent — green. Actions, completion, KPIs all share it */
  --accent: #03c75a;  --accent-strong: #02a148;
  --accent-soft: #e5f8ec;  --accent-text: #02663d;

  /* Warning — soft gold, not harsh amber */
  --warn: #f59e0b;  --warn-soft: #fff8e6;  --warn-text: #a16207;

  /* Danger */
  --danger: #ef4444;  --danger-soft: #fff1f1;  --danger-text: #b91c1c;

  /* Radii — deliberately large */
  --radius-sm: 8px;  --radius: 12px;  --radius-lg: 16px;
  --radius-xl: 20px; --radius-2xl: 24px; --radius-full: 999px;

  /* Shadows — very subtle, blue-tinted black */
  --shadow-xs: 0 1px 2px rgba(0, 23, 51, .04);
  --shadow-sm: 0 2px 8px rgba(0, 23, 51, .04);
  --shadow-md: 0 4px 16px rgba(0, 23, 51, .06);
  --shadow-lg: 0 8px 24px rgba(0, 23, 51, .08);

  --nav-height: 52px;   /* single source of truth — hero video overlaps the navbar */
}
```

## The `trust` theme

Company default is green. Setting `data-theme="trust"` on a root element switches
**accent and info to blue** — used where the product needs to read as institutional
rather than energetic.

```css
[data-theme='trust'] {
  --accent: #3182f6;  --accent-strong: #1b64da;
  --accent-soft: #e8f3ff; --accent-text: #1957c9;
  --info: #3182f6;  --info-soft: #e8f3ff;  --info-text: #1957c9;
}
```

**`--green-*` stays green in both themes on purpose.** It carries meaning — verified,
environmental, complete — so it must not follow the accent, or a theme switch would
silently change what a screen asserts.

## Rules that fall out of this

- **One accent.** `--accent`, `--green`, and `--info` are the same green by default.
  Adding a fourth signal color breaks the "quiet surfaces, one loud accent" premise.
- **Never pure black text.** `#191f28` is the darkest text. `#000` looks harsh against
  these grays.
- **Borders separate, they do not decorate.** `--border` is `#f2f4f6` — almost the same
  as `--bg-subtle`. If a border needs to be seen, the layout is doing too little.
- **Radius scales with the element.** Chips 8px, cards 12–16px, sheets 20–24px, pills
  full. Mixing radii within one component reads as a mistake.
- **Semantic colors keep their meaning.** Do not reuse `--danger` for a decorative red.

## Why it is built this way

The palette is tuned for **Korean product interfaces**, where a few things differ from
Latin-first systems:

- **Cool grays, not warm or neutral.** Hangul at body size has heavier visual mass than
  Latin. A warm gray behind it turns muddy; the slight blue in `#4e5968` keeps dense text
  readable without raising contrast to the point of harshness.
- **No pure black.** `#191f28` is the floor. Korean typefaces have thicker strokes and
  fewer weights, so `#000` on white reads as heavier than the same text in Latin.
- **Large radii, almost no borders.** With `--border` at `#f2f4f6`, separation comes from
  the surface step (white card on `--bg-soft`) rather than a line. Fewer lines means less
  visual noise competing with dense Hangul.
- **One accent, used everywhere.** Actions, completion, and KPIs share a single green, so
  color means "this matters" rather than "this is a category". A second signal color
  would force readers to learn a legend.

Pair it with the Korean typography notes in `design-systems.md` — line-height 1.6–1.7 and
negative heading tracking are assumed by this palette, not optional with it.

## Using it outside ZEST

Free to use. The token block above is the whole system — copy it, rename the variables,
and change the accent to your own.

Two things to keep if you want the character to survive: **the surface step** (white on
cool gray, borders nearly invisible) and **the single accent**. Those two do most of the
work. The specific green is the least important part; it is the one thing you should
replace to avoid looking like someone else's product.
