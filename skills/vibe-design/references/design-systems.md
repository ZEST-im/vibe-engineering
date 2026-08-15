# Design system catalog

Start from a system that already exists. **AI-generated design looks generic because the
model invents a design language from nothing every time** — a real color ramp, a real type
scale, and a real spacing rhythm remove that step.

What you take is the **token layer**, not components. Tokens inline cleanly, so the
self-contained rule still holds.

> Everything below was fetched and checked on **2026-08-15**. Licenses come from each
> repository, not from memory. Re-check before relying on a license.

---

## Neutral token sets — safe default when the product has no brand yet

| System | License | Source | What you get |
|---|---|---|---|
| **Radix Colors** | MIT | `unpkg.com/@radix-ui/colors/<hue>.css` | 12-step ramps per hue, light + dark, built for contrast pairs. ~1KB per hue |
| **Open Props** | MIT | `unpkg.com/open-props/open-props.min.css` | Sizes, colors, shadows, easings, gradients in one 29KB file |
| **Tailwind palette** | MIT | `tailwindcss.com/docs/colors` | The most recognizable ramps. Familiarity cuts both ways — it is also the most common "AI look" |

Radix is the best first choice when you need color you can reason about: each step has a
defined job (1–2 backgrounds, 3–5 component fills, 6–8 borders, 9–10 solid, 11–12 text).

## Product and admin systems — dense screens, many states

| System | License | Source | Character |
|---|---|---|---|
| **Primer** (GitHub) | MIT | `unpkg.com/@primer/primitives/dist/css/functional/themes/light.css` | Developer tools. Functional token names, light/dark parity. 121KB |
| **Carbon** (IBM) | Apache-2.0 | `unpkg.com/@carbon/colors/lib/index.js` | Enterprise data. Strict grid, restrained color |
| **Polaris** (Shopify) | check repo | `unpkg.com/@shopify/polaris-tokens/dist/css/styles.css` | Commerce admin. `--p-color-*` semantic naming. 28KB |
| **Spectrum** (Adobe) | check repo | `unpkg.com/@adobe/spectrum-tokens/dist/json/variables.json` | 2,469 tokens. Rich but heavy — take a slice, not the file |
| **Atlassian** | check repo | `unpkg.com/@atlaskit/tokens/dist/esm/artifacts/token-names.js` | Names only; values need the theme package |

GitHub could not auto-classify the Polaris and Spectrum licenses. **Read their LICENSE
before shipping anything derived from them.**

## Public sector and accessibility

| System | License | Source | Why |
|---|---|---|---|
| **USWDS** | US Gov work (GitHub: NOASSERTION) | `unpkg.com/uswds/dist/scss/theme/_uswds-theme-color.scss` | Contrast and target sizes already validated against federal requirements |
| **GOV.UK Frontend** | MIT | `github.com/alphagov/govuk-frontend` | Plain-language typography, tested with low-confidence users |

Reach for these when the audience is older, non-expert, or legally entitled to access —
the floors are already argued for, so you inherit the argument.

## Palettes only

| System | License | Source |
|---|---|---|
| **Catppuccin** | MIT | `unpkg.com/@catppuccin/palette/css/catppuccin.css` — 4 flavors, 18KB |

---

## Korean systems

Verified 2026-08-15. **Most Korean design systems do not publish tokens.**

| System | Status | Notes |
|---|---|---|
| **SEED** (당근) | ✅ Apache-2.0, ★1045 | The only Korean system found with open, extractable token values |
| **KRDS** (정부) | ❓ unverified | `krds.go.kr` responds, but the page is JS-rendered so a raw fetch shows no tokens or downloads. Do not claim it has them |
| **ZEST UI** | ✅ documented | Cool-gray surfaces, single accent, large radii — see `zest-ui.md`. Free to use |

Several large Korean products publish only brand or partner guidelines — logo usage,
integration rules — rather than tokens. Those are worth reading when you integrate with
a platform, but they are not a visual starting point and are not listed here.

### SEED (당근) — the one that works

```bash
curl -sL https://unpkg.com/@seed-design/stylesheet@1.1.2/global.css
```

51KB, 74 CSS variables with real hex values:

```css
--seed-scale-color-gray-00: #ffffff;
--seed-scale-color-gray-50: #f7f8fa;
--seed-scale-color-carrot-50: #fff5f0;   /* brand ramp */
```

Two layers: `--seed-scale-*` (raw ramps) and `--seed-semantic-*` (roles like
`primary`, `warning`). **Take the scale layer and map your own semantics** — the carrot
ramp is 당근's brand, not yours.

The `@seed-design/design-token` package holds only `var()` references, not values, so
the stylesheet package is the one you want. Dark theme is not in `global.css`; check
`@seed-design/css` if you need it.

### Korean typography

No token set solves this. Check regardless of which system you start from:

- **Line height needs more room.** Hangul has no ascender/descender rhythm to lean on;
  Latin-tuned 1.4–1.5 reads tight. Start at 1.6–1.7 for body text.
- **Weights are coarser.** Most Korean web fonts ship 3–4 weights, not 9. A scale that
  distinguishes 500 from 600 will collapse.
- **Letter-spacing negative on headings.** Large Hangul at default tracking looks loose;
  around `-0.02em` is a common correction.
- **No italics.** Korean typefaces do not have true italics. Use weight or color instead.

---

## Picking one

Let the product decide, not taste.

| If the product is | Start from |
|---|---|
| Public service, older or non-expert users | USWDS or GOV.UK |
| Dense internal tooling, tables, many states | Primer or Carbon |
| Commerce or merchant-facing admin | Polaris |
| Korean consumer product | SEED scale layer + Korean typography checks |
| Korean product wanting quiet surfaces and one accent | `zest-ui.md` |
| Nothing decided yet | Radix Colors + Open Props |

Then **make one deliberate move that belongs to this product and nothing else** — a
material, a place, an instrument from its world. The borrowed system keeps you from
inventing badly; the one move keeps you from looking like everyone else.
