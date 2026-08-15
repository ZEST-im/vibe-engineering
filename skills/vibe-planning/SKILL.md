---
name: vibe-planning
description: Project kickoff planning — walks a developer through five gated stages, from north star to screens, asking one question at a time. Use when starting a new project, product, or major subsystem and the planning work has to happen alongside the building.
user-invocable: true
---

# Vibe Planning — Kickoff Planning in Five Gates

For developers who have to do the planning too. You ask the questions; the developer
answers; each stage produces one short document. Five stages, five artifacts, no more.

**Write every artifact in the language the user is working in.** The templates below use
English headings; mirror them in the user's language when that is what they write in.

## Non-negotiables

- **One question per message.** Use `AskUserQuestion`. Every option carries a short
  description saying *why the question matters* — the user may not think like a planner.
- **One stage at a time.** Do not draft stage N+1 before stage N is approved. Early
  answers change later documents; batching the questions produces documents that
  contradict each other.
- **Respect the size caps.** They are the point. A planning skill that produces a
  20-page deck has failed at the job.
- **Never invent facts.** If the user does not know something, it goes in the open
  questions table marked `[assumption]` — it does not get quietly filled in.

## Where things go

All artifacts land in the target project's `docs/planning/`:

```
docs/planning/
  01_philosophy.md        north star
  02_requirements.md      features + acceptance + out of scope
  03_user_stories.html    stories by role
  04_screens.html         landing + key screens (built by vibe-design)
  05_tech_decisions.md    decisions + reversal cost
```

## Resume protocol

There is no state file. On invocation, list `docs/planning/` and start at the first
stage whose artifact is missing. Say which stage you are resuming at before asking
anything. If the directory does not exist, start at stage 1.

## Size caps

| Stage | Questions | Artifact | Cap |
|---|---|---|---|
| 1 North star | 6–8 | `01_philosophy.md` | 2 pages |
| 2 Requirements | 4–6 | `02_requirements.md` | 3 pages |
| 3 User stories | 3–4 | `03_user_stories.html` | 12 stories |
| 4 Screens | 2–3 | `04_screens.html` | 5 screens |
| 5 Tech decisions | 4–5 | `05_tech_decisions.md` | 2 pages |

---

## Stage 1 — North star

The document every later decision gets checked against. Ask, in order:

1. In one line: this is *what*, for *whom*?
2. How do those people do this today? (What is the real alternative — a spreadsheet, a
   person, nothing?)
3. Where does that way structurally break down? Name the specific points of failure.
4. What do you believe that a competitor would disagree with?
5. Who is explicitly **not** your user?
6. Six months out, what has to be true for this to have worked? (short-term)
7. And what would make it *actually* worth having built? (the real one)
8. What does the name mean? (skip if there is no name yet)

### Required structure

Three elements below are **mandatory**. If any is empty, the stage is not done — go back
and ask. They are what separates this document from a generic product brief.

```markdown
# <Product> — Philosophy
> North star · the standard every product decision is checked against

## In one line
> **<one sentence>**

## The world as we see it
<the problem, structurally — where does it break and why>

## What we believe
<the beliefs a competitor would argue with>

## What it does
<capabilities at concept level — not a feature list>

## Our user
<who they are>

**Who we are not for**            ← MANDATORY
<the segment you are deliberately not serving, and why that is fine>

## Product principles                ← each one MANDATORY carries a test
**1. <principle>**
<explanation>
> **Judgment test:** "<a question answerable yes/no>" — if <answer>, then <what you do>.

## What success means
**Short term** — <the near milestone>
**The real one** — <the outcome that would make it worth it>

## Open questions                    ← MANDATORY
| Open question | Where it stands | How it gets settled |
|---|---|---|
| <item> | <status, `[assumption]` on any unbacked number> | <what would settle it> |
```

The judgment test is the hard part and the most valuable. A principle without one is
decoration. Push for a test the developer could actually apply in an argument next month
— "would a site foreman type this in himself? If no, it has to be automatic" beats
"we value usability."

Draft it, show it, get approval, then move on.

---

## Stage 2 — Requirements and features

1. Break the north star's "what it does" into discrete features. Which are they?
2. First release: which are must-have, which can wait?
3. For each must-have, what *observable* thing proves it is done?
4. Which non-functional constraints are real (scale, latency, security, compliance) —
   as opposed to aspirational?
5. What are you explicitly *not* building in this release?

Output `02_requirements.md`: a feature table (`ID | Feature | M/S/C | Done when`), a
short non-functional section, and an explicit out-of-scope list. Acceptance criteria must
be observable — "fast" is not one, "search returns in under 300ms at 10k rows" is.

---

## Stage 3 — User stories

1. What are the 2–3 user roles?
2. For each, the path from arriving to their first success?
3. Where do you expect them to get stuck?

Output `03_user_stories.html` — self-contained HTML, no external references. Story cards
grouped by role, each with Given/When/Then acceptance criteria. Twelve stories maximum;
if you have more, the release is too big — say so and cut.

---

## Stage 4 — Screens and landing

1. What must a visitor understand within three seconds of the landing page?
2. Which 3–5 screens carry the product?
3. What tone — where on trust / speed / expertise / warmth?

**Hand off to the `vibe-design` skill** to produce `docs/planning/04_screens.html`. Do not
draw the screens yourself here. Nothing gets implemented before the user has looked at
them in a browser and approved.

---

## Stage 5 — Technical decisions

1. What stack does the team already run well?
2. What technical constraint does this product make unavoidable?
3. What is the source of truth for the data, and where does it live?
4. Who deploys and operates it, how?
5. Which decision here is the most expensive to reverse?

Output `05_tech_decisions.md`: a decision table (`Decision | Choice | Why | Reversal
cost`), an ASCII architecture sketch, and open questions. Spend the care on the
expensive-to-reverse rows; note the cheap ones and move on.

---

## Finishing

1. List the five artifacts with their paths.
2. Name what is still open across all of them — the `[assumption]` rows especially.
3. **Propose** follow-up implementation tasks for the kanban, derived from stage 2's
   must-haves. Show the list and ask before writing them. Do not create tasks
   unprompted. Follow the task field rules in the `vibe-harness` skill.

## Red flags

| Thought | Reality |
|---|---|
| "I'll ask everything up front, then write all five" | Later answers depend on earlier documents. Gate by gate. |
| "The principle is clear enough without a test" | A principle you cannot apply in an argument is decoration. |
| "They didn't say who they're *not* for, I'll skip it" | That section is where scope discipline comes from. Ask again. |
| "I'll estimate the market size to fill the gap" | Unbacked numbers go in the open questions table marked `[assumption]`. |
| "Wireframes can wait until after implementation starts" | Stage 4 exists because building without seeing the screen is how work gets thrown away. |
