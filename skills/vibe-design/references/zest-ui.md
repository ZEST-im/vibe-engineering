# ZEST UI — design language

> Source: `@zest-im/ui` → `src/styles/tokens.css`, read 2026-08-15.
> **Internal.** The package ships through private GitHub Packages and needs a token.
> This file records the language so ZEST products stay coherent even where the package
> is not installed.

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

## Provenance

The token file records where the values came from: cool grays and the large-radius,
low-shadow treatment follow **Toss**, the green is **Naver Pay green** (`#03c75a`, which
[verified on Naver's own design page](https://developers.pay.naver.com/design/brand/logo)),
and the `trust` blue matches **Toss blue** (`#3182f6`, verified on Toss's guide).

Two cautions:

- Those are **other companies' brand colors**. They are used here as ZEST's palette; do
  not present ZEST work as affiliated with either company.
- The gray ramp attribution is what the token file's own comments claim.
  **It could not be verified against a Toss source** — their published guide is
  documentation hosted on GitBook and does not expose their tokens. Treat the grays as
  ZEST's values, not as a Toss citation.
