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

**This skill owns two things:** the *ordering rule* (nothing gets implemented before the
screen has been seen and approved) and the *artifact format* (self-contained HTML on
disk).

**It does not own aesthetics.** For visual direction — typography, color, layout,
avoiding templated defaults — use the `frontend-design` skill and follow it. Do not
reinvent design principles here.

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

1. What must a visitor understand within three seconds of the landing page?
2. **Which user groups are in this round?** Name them and their axes (above). If the
   answer is one, ask once more — a second group is usually hiding behind a feature
   nobody called a screen.
3. Which screens are in this round, **per group**? (five maximum per group)
4. Tone — where does this sit on trust / speed / expertise / warmth? Ask whether the
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
| "I'll pick the colors and typography myself" | Load `frontend-design` and follow it. |
| "There's only one user group here" | There are usually two. Ask again before believing it. |
| "The second group just needs a simpler version of the main screen" | It is a different surface, not a subset. Shrinking the dashboard never produces the form. |
| "Both groups can share the five screens" | Then both get half a product. Five per group. |
