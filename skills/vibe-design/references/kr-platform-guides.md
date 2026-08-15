# Korean platform guides — Naver Pay, Toss

> Checked 2026-08-15.
>
> **These are not design systems to design like.** Both are partner-facing rulebooks:
> what you must follow when your product appears *inside* their platform. Read them when
> you are integrating, not when you are looking for a visual direction. For direction,
> use `design-systems.md`.

Getting this wrong has consequences beyond taste — both carry usage restrictions.

---

## Naver Pay — brand and logo guide

`developers.pay.naver.com/design/brand/logo`

A **logo usage guide for partner merchants**, not a token set. What it governs:

- Logo variants: signature, badge, symbol, button, overseas-merchant, benefit badge, bridge
- Default treatment is the **black logo on a green field**; white or black is allowed when
  the medium demands legibility
- Naver green on a white background is a **limited exception**, permitted only when the
  normal rule cannot be applied
- Minimum clear space is defined by the spacing between logo elements; nothing else may
  enter it
- A small-size logo exists and is only for **20px / 4mm and below**
- Assets must not be modified

**Verified value:** Naver green `#03c75a` appears on the page itself.

**Eligibility:** the guide states the logo may be used **only by Naver Pay partners**
(협력사). If you are not one, you may not put it on a screen — including a mockup that
will be shown outside the team.

### When this matters to a design round

Building a Naver Pay integration. Then the payment entry point is not yours to style:
use the specified variant, respect the clear space, and do not tint it to match your
palette.

---

## Toss — Apps in Toss (앱인토스) mini-app guide

`developers-apps-in-toss.toss.im/design/consumer-ux-guide`

A **UI/UX rulebook for third-party mini-apps running inside the Toss app**. Its stated
purpose is that users can tell your service apart from Toss itself. It covers brand
logo/name/color, dark-pattern prevention, UX writing, graphic resources, and resolution
standards.

Concrete requirements seen on the page:

- Brand logo must be **600×600px, square with hard corners** — rounded shapes are rejected
- The logo needs a background that works in **both light and dark mode**
- If the artwork already includes a background, it must **fill the 600×600 area**
- The same logo URL goes in the console **and** in `granite.config.ts` under
  `appsInToss` → `brand.icon`
- Your brand logo, name, and color must be visible throughout, specifically so users do
  **not** confuse your service with Toss

**TDS (Toss Design System)** is offered as a UI Kit for mini-apps — components include
`Border`, `BottomCTA`, `Button`, `ListRow`, `ListHeader`, `Paragraph`, with Figma
resources. The page carries a **license notice**: using the UI Kit means accepting its
terms.

**Verified value:** Toss blue `#3182f6` appears on the page.

**Not available:** Toss does not publish design tokens. `toss/tds` does not exist on
GitHub; the repositories that appear in search are unofficial third-party clones with
almost no adoption. Do not cite them.

### When this matters to a design round

Building an Apps-in-Toss mini-app. Then the constraint is inverted from normal work:
your job is to look **clearly not like Toss** while sitting inside their shell. Brand
separation is a requirement, not a preference, and the 600×600 hard-cornered icon is a
hard spec.

---

## Summary

| | What it is | Use it when | Do not |
|---|---|---|---|
| Naver Pay | Logo/brand rules for partners | Integrating Naver Pay | Use the logo without partner status; retint it |
| Toss / 앱인토스 | Mini-app UI/UX rules + licensed UI Kit | Shipping inside the Toss app | Treat TDS as open tokens; cite third-party clones |

Neither belongs in a "make it look like X" conversation. If someone asks for a Toss-like
or Naver-like feel, take that as a request for **direction** — cool grays, large radii,
quiet borders, one strong accent — and build it from the catalog instead.
