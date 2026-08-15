---
name: vibe-design
description: Build the landing page and key screens as self-contained HTML and look at them in a browser before any implementation starts. Use when a screen, landing page, or UI flow is about to be built, or when vibe-planning reaches its screens stage.
user-invocable: true
---

# Vibe Design — See the Screen Before You Build It

Building a screen you have never seen is how work gets thrown away. This skill puts one
gate in front of implementation: the screen exists as HTML, it opened in a browser, and
the user approved it.

## What this skill is and is not

**This skill owns three things:** the *ordering rule* (nothing gets implemented before the
screen has been seen and approved), the *artifact format* (self-contained HTML on disk),
and *where the design language comes from*.

That third one is the difference between a usable mockup and AI slop.

## Do not invent a design language

Generated design looks generic for a specific reason: **the model invents a color ramp, a
type scale, and a spacing rhythm from nothing on every run.** Invented-from-nothing
converges on the average — that is what "AI slop" is.

The fix is not to try harder. It is to **start from something that already exists**, take
its token layer, and then make one deliberate move that belongs to this product.

### Ask where the starting point comes from — first, before anything else

This question decides everything downstream, so ask it before the three-second message,
before screens, before tone. **There are two paths, and both end in real values.**

| Path | What you get |
|---|---|
| **A. Catalog** *(default)* | A system from `references/design-systems.md`, picked by what the product is. Real token files, checked licenses |
| **A′. House system** | If the org has one — e.g. `references/zest-ui.md` — start there and skip the catalog |
| **B. A link** | You fetch the page and read its actual CSS |

**Prefer A.** The catalog entries are token sets built to be reused, with licenses already
checked. A link gives you one site's finished decisions, which are tuned to that site's
brand and not necessarily coherent as a system.

**Path B — a link.** Fetch the page and pull real values rather than eyeballing it:
custom properties in `:root`, the `font-family` stack, and the colors that actually
repeat. Tell the user which values you extracted and which you inferred.

Take *direction* — density, warmth, rhythm, structure. Do not reproduce someone's
product. Their logo, brand color, and distinctive layout are theirs. If the request is
effectively "clone this site", say so and offer the direction instead.

**Do not work from a screenshot.** You cannot recover exact hex values or a type stack
from an image, and an approximation that looks precise is worse than no starting point —
nobody can reproduce it, and the drift shows up in implementation. If the user has only a
screenshot, ask for the URL; if there is none, use the catalog and treat the image as
tone reference only, saying that is what you are doing.

### Then, whichever path

1. **Read the actual values.** Do not describe a design system or a site from memory.
2. **Take the scale layer, map your own semantics.** A borrowed brand ramp is the other
   company's brand. Their gray scale is reusable; their primary is not.
3. **Make one move that is this product's.** A material, a place, an instrument from the
   product's own world — and spend your boldness only there. In a system for elderly
   community centres, the status indicator became a heated floor, because the product is
   about whether a floor is warm.

**If the product ships inside another company's platform** (a Naver Pay integration, an
Apps-in-Toss mini-app), read `references/kr-platform-guides.md` first. Those platforms
impose hard requirements — asset specs, clear space, brand-separation rules — that
override design preference, and one of them requires partner status to use at all.

If the fetch fails or you are offline, say so and fall back to Radix-style reasoning —
12 steps with defined jobs — rather than picking colors freehand.

**Restraint:** everything except the one deliberate move stays quiet. If two things are
shouting, neither is a signature.

## Two audiences is the normal case

Most products have two user groups, not one. A monitoring tool has the operator and the
person on site. A booking tool has the staff and the customer. Assume two until the user
tells you there is one.

**The secondary group is not a stripped-down version of the primary one.** That is the
mistake this section exists to prevent. An operator dashboard and a once-a-year QR form
are different surfaces with different rules, and shrinking the dashboard does not produce
the form.

Before drawing, name each group along these axes — they decide the design, not taste:

| Axis | Why it changes the screen |
|---|---|
| **Frequency** | Daily users learn the interface; one-time users never do. Labels a daily user finds redundant are the only thing a one-time user has. |
| **Training** | A trained operator can read a dense readout. Someone who scanned a code cannot be taught anything. |
| **Actions available** | Count them. If the secondary group has one action, the screen has one button and nothing else competing with it. |
| **Stakes** | Deciding something needs evidence on screen. Reporting something needs the shortest path to done. |
| **Body** | Age, gloves, sunlight, one hand. These set the floors below, and they are not negotiable. |

**Floors for infrequent or non-expert groups:** body text at least 18px, tap targets at
least 44px, one primary action per screen, no horizontal scrolling, and a visible
confirmation that the action worked. Do not make these depend on the user's eyesight or
patience.

Both groups share **one token set** — same palette, same type families, so it is
recognisably one product. What differs is the **scale and density** applied to those
tokens, not the tokens themselves. If you find yourself inventing a second palette, the
product has split in two and that is a planning question, not a design one.

## Where things go

- Called from `vibe-planning` stage 4 → `docs/planning/04_screens.html`
- Standalone on an existing project → `docs/design/<name>.html`

Create the directory if it does not exist. One file holds all the screens for the round.

## Before drawing anything

Read what already exists, in this order — skip what is absent:

1. `docs/planning/01_philosophy.md` — who the user is, who they are *not*, the tone.
2. `docs/planning/03_user_stories.html` — what each screen has to let someone accomplish.
3. The project's existing UI (design system doc, current templates, screenshots) so a new
   screen does not clash with what is shipped.

Then confirm these with the user, one question per message:

1. **Where does the design language start?** — catalog (default) or a link (see above).
   Ask this first; it changes every answer that follows.
2. What must a visitor understand within three seconds of the landing page?
3. **Which user groups are in this round?** Name them and their axes (above). If the
   answer is one, ask once more — a second group is usually hiding behind a feature
   nobody called a screen.
4. Which screens are in this round, **per group**? (five maximum per group)
5. Tone — where does this sit on trust / speed / expertise / warmth? Ask whether the
   tone differs by group; an outward-facing landing and an internal readout often want
   opposite things.

## Artifact rules

- **Self-contained.** No CDN scripts, no external stylesheets, no remote fonts, no remote
  images. Inline everything; embed images as `data:` URIs. The file must render offline,
  because it lives in git and gets opened months later as the reference for what was
  agreed.
- **Both themes.** Define the light palette on `:root`; override under
  `@media (prefers-color-scheme: dark)`. Give `body` an explicit background — never rely
  on the browser's default.
- **Responsive.** Relative units, `max-width: 100%` on images. The page body must never
  scroll horizontally; wide tables and code blocks scroll inside their own container.
- **Five screens maximum per user group**, and each group gets its own labelled section
  in the file. Each screen gets a heading with its name and a one-line statement of its
  purpose. More than five in one group means that group's round is too big — say so and
  split it. Do not make two groups share a budget of five; that produces two thin halves
  instead of one working product.
- **Show the groups side by side where it matters.** When the same event appears to both
  groups — a request raised by one and handled by the other — draw both views near each
  other. Divergence between them is the bug this skill catches earliest.
- **Real content, not lorem ipsum.** Use the actual product's words from
  `01_philosophy.md`. Placeholder text hides the fact that the real copy does not fit.
- **Draw the states, not just the happy path.** For every screen that loads or submits
  anything, show what it looks like **empty, loading, failed, and full**. These are where
  implementations actually break, and a mockup that skips them has not done its job.
  A list with three rows tells you nothing about the same list with three hundred.

## Leave the tokens behind

The HTML is the artifact, but it is not the handoff. At the top of the file, record the
token block you actually used — palette, type stack, spacing, radii — as CSS custom
properties in one `:root`, and note which system they came from.

```css
/* Tokens — derived from Radix Colors (MIT), fetched 2026-08-15.
   Product move: ondol floor as the status surface. */
:root { --bg: …; --fg: …; --accent: …; }
```

Two reasons. The implementer needs the values, not screenshots of them. And the next
round of screens must reuse the same tokens or the product drifts apart.

## Show it

Write the file, then open it:

```bash
open docs/planning/04_screens.html        # macOS
xdg-open docs/planning/04_screens.html    # Linux
start docs/planning/04_screens.html       # Windows
```

Tell the user the path and what you want them to judge — not "how does it look" but
"does the hero say the right thing in three seconds", "is this the flow you meant".

## Iterate

Feedback → edit the same file → open again → ask again. Keep the same path so the git
history shows the screen evolving.

**Do not start implementing while the screen is unapproved.** That is the whole point of
the skill. When the user approves, say explicitly which screens were approved, then hand
back to whatever invoked this.

## Red flags

| Thought | Reality |
|---|---|
| "I'll pull in Tailwind from a CDN, it's faster" | The file has to render offline in a year. Inline it. |
| "Lorem ipsum is fine for the layout" | Real copy is how you find out the layout does not fit. |
| "I'll build the component and design it as I go" | That is the failure this skill exists to prevent. |
| "The user described it clearly, they don't need to see it" | Descriptions and screens diverge. Show it anyway. |
| "Ten screens in one file is more efficient" | Five is the cap *per group*. More means split the round. |
| "I'll pick the colors and typography myself" | That is how slop happens. Start from a real system in the catalog. |
| "I'll describe that design system from memory" | Fetch it. The catalog has checked URLs and licenses. |
| "They only have a screenshot, I'll work from that" | Ask for the URL. If there is none, use the catalog and treat the image as tone only. |
| "They sent a link, so I'll match it closely" | Take direction, not their product. Logo, brand color, and distinctive layout are theirs. |
| "The happy path is enough to approve" | Empty, loading, and error states are where implementations break. Draw them. |
| "I'll make several things distinctive" | Spend boldness once. Two signatures is none. |
| "There's only one user group here" | There are usually two. Ask again before believing it. |
| "The second group just needs a simpler version of the main screen" | It is a different surface, not a subset. Shrinking the dashboard never produces the form. |
| "Both groups can share the five screens" | Then both get half a product. Five per group. |
