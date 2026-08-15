---
name: vibe-planning
description: Project kickoff planning — walks a developer through gated stages, from north star to a scaffolded project, asking one question at a time. Use when starting a new project, product, or major subsystem and the planning work has to happen alongside the building.
user-invocable: true
---

# Vibe Planning — Kickoff Planning in Six Gates

For developers who have to do the planning too. You ask the questions; the developer
answers; each stage produces artifacts. Planning ends with a project you can start
building in, not with a folder of documents.

**Write every artifact in the language the user is working in.** The templates below use
English headings; mirror them in the user's language when that is what they write in.

## Non-negotiables

- **One question per message.** Use `AskUserQuestion`. Every option carries a short
  description saying *why the question matters* — the user may not think like a planner.
- **Options are capped at four.** When there are more candidates, group them and label
  the last option `(계속)` / `(more)` so the user knows the list was compressed. Never
  drop a candidate silently — grouping is already an act of planning, so say you did it.
- **One stage at a time.** Do not draft stage N+1 before stage N is approved.
- **Respect the size caps.** A planning skill that produces a 20-page deck has failed.
- **Never invent facts.** If the user does not know something, it goes in the open
  questions table marked `[assumption]` — it does not get quietly filled in.
- **Never invent priorities.** If you did not ask whether something is must-have, it has
  no priority. Write "priority not yet decided" instead of guessing a grade.

## The authorship rule

You will end up drafting sentences the user never said — principles especially. Approval
of your draft is **not** the same as the user having said it.

Mark every element you authored rather than elicited, and ask the user to confirm each
one *as their own claim*:

> 아래 원칙 3개는 제가 답변에서 유도해 문장으로 쓴 것입니다. 당신이 실제로 그렇게
> 믿는지 하나씩 확인해 주세요 — 제가 쓴 문장을 검토하는 것과, 당신이 그렇게 믿는다고
> 말하는 것은 다릅니다.

A principle the user did not actually hold will silently contradict a feature three
stages later, and by then four documents depend on it.

## Where things go

Planning artifacts land in the target project's `docs/planning/`. Stage 6 writes the
project scaffolding at the repo root and in `docs/`.

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

**Redoing a stage invalidates every stage after it.** File presence means "this stage is
settled", so a stale downstream artifact reads as settled when it is now false. Before
reworking stage N, delete the artifacts for N+1 onward and tell the user which ones you
removed. Never edit a downstream document to patch over a changed north star — the
questions that produced it were asked under the old premise, so it has to be re-asked,
not repaired.

## Size caps

| Stage | Questions | Artifact | Cap |
|---|---|---|---|
| 1 North star | 8–10 | `01_philosophy.md` | 2 pages |
| 2 Requirements | 4–6 | `02_requirements.md` | 3 pages |
| 3 User stories | 3–4 | `03_user_stories.html` | 12 stories |
| 4 Screens | 2–3 | `04_screens.html` | 5 screens |
| 5 Tech decisions | 4–5 | `05_tech_decisions.md` | 2 pages |
| 6 Scaffolding | 3–4 | see stage 6 | — |

---

## Stage 1 — North star

The document every later decision gets checked against. Ask, in order:

1. In one line: this is *what*, for *whom*?
2. **What else does it do?** Name every capability, not just the obvious one.
   Then ask again: "is that all?" — see the scope trap below.
3. How do those people do this today? (What is the real alternative?)
4. Where does that way structurally break down? Name the specific points of failure.
5. **Who touches this product?** List every role — including people who are not the
   buyer and may only interact once. For each, does that role need its own screen?
6. What do you believe that a competitor would disagree with?
7. Who is explicitly **not** your user?
8. **Where does the first deployment actually happen?** One site, one team, one city —
   be concrete. This constrains everything downstream.
9. Six months out, what has to be true for this to have worked? (short-term)
10. And what would make it *actually* worth having built? (the real one)
11. What does the name mean? (skip if there is no name yet)

### The scope trap

**The product name will mislead you.** A name containing "monitoring" makes you ask only
about monitoring; a name containing "chat" makes you ask only about messaging. You will
build an entire document set inside that frame and only discover the missing half when
the user looks at a screen and says "where is the other thing?"

Question 2 exists to break this. Ask it as an open list, and after the user answers,
**ask once more whether anything is missing.** Do not proceed to question 3 until the
user has had a second pass at the capability list.

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
<every capability, at concept level — the full list from question 2>

## Who touches it
<every role, and whether it needs its own screen>

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

**Before writing a principle, check it against every capability from question 2.** A
principle that contradicts a capability is how the whole document set goes wrong.

Draft it, apply the authorship rule, get approval, then move on.

---

## Stage 2 — Requirements and features

1. Break the north star's "what it does" into discrete features — **all capabilities,
   not just the first one.**
2. First release: which are must-have, which can wait?
3. For each must-have, what *observable* thing proves it is done?
4. Which non-functional constraints are real (scale, latency, security, compliance,
   device) — as opposed to aspirational?
5. What are you explicitly *not* building in this release?

Output `02_requirements.md`: a feature table (`ID | Feature | Priority | Done when`), a
short non-functional section, and an explicit out-of-scope list.

**Priority grades:** `M` = this release fails without it. `S` = planned, next release.
`C` = wanted, unscheduled. Only assign a grade the user actually gave you. Everything
else goes under "priority not yet decided" — never infer a grade from the order things
were mentioned.

Acceptance criteria must be observable — "fast" is not one, "search returns in under
300ms at 10k rows" is. Keep "what we decided *not* to decide" separate from "what we
decided against"; conflating them turns silence into a decision nobody made.

---

## Stage 3 — User stories

1. Confirm the roles from stage 1 question 5. Which are in this release?
2. For each, the path from arriving to their first success?
3. Where do you expect them to get stuck?

Output `03_user_stories.html` — self-contained HTML, no external references. Story cards
grouped by role, each with Given/When/Then acceptance criteria. Twelve stories maximum;
if you have more, the release is too big — say so and cut.

**Every role that needs its own screen needs its own stories.** A role you cannot write
a story for is a role you do not understand yet — go back and ask.

---

## Stage 4 — Screens and landing

1. What must a visitor understand within three seconds of the landing page?
2. Which 3–5 screens carry the product? **Check the role list — each role that needs
   its own screen needs one here.**
3. What tone — where on trust / speed / expertise / warmth?

**Hand off to the `vibe-design` skill** to produce `docs/planning/04_screens.html`. Do not
draw the screens yourself here. Nothing gets implemented before the user has looked at
them in a browser and approved.

---

## Stage 5 — Technical decisions

**This is the stage where the person you are helping is most likely to be out of their
depth, and it is where this skill is worth the most.** Someone who is not an
infrastructure engineer does not know which decisions exist. They cannot ask about
authentication infrastructure or object storage if nobody told them those are choices.
Your job is to name every decision, explain what it does in one line, say what breaks if
it is wrong — and then decide it together.

**Walk the checklist. Do not skip an item because the user did not raise it** — not
raising it is the symptom you are treating.

| Decision | What it is | What goes wrong |
|---|---|---|
| Backend language & framework | What the server is written in | Wrong pick and the team cannot maintain it |
| Frontend approach | Server-rendered, SPA, or native | Decides how much frontend work exists at all |
| Database | Where records live | Hardest thing to migrate later |
| Data acquisition | How external data arrives — devices, APIs, uploads, polling vs push | Silent gaps nobody notices |
| File & media storage | Where photos and documents go | Filling the app server's disk in production |
| Cloud infrastructure | Where it runs, which account owns it | Procurement and security blockers, surprise bills |
| Authentication | Who signs in, and which paths stay anonymous | Retrofitting auth touches every screen |
| Background jobs | Work that happens off the request | Timeouts and lost work under load |
| Build & release | CI, migrations, rollback | No safe way to ship a fix |
| Monitoring & alerting | What is watched, who gets woken | Outages found by users |
| Cost model | What scales with what | A pilot that cannot afford to become a rollout |

Ask one decision at a time. Offer real options **with their trade-offs spelled out** —
this is teaching, not a poll. State a recommendation and the reason for it, and make it
easy to say "I don't know yet."

Then close with:

1. What are you already running well, and what would you rather not add?
2. What technical constraint does this product make unavoidable?
3. Which decision here is the most expensive to reverse?

### Always record the version

**Every technology named in this stage carries an explicit version.** "PostgreSQL" is not
a decision; "PostgreSQL 17" is. A stack recorded without versions looks settled and is
not — the next person installs whatever is current that week, and the gap only surfaces
when something breaks.

- Write the version in the decision table, in the architecture sketch, and in every
  scaffolding file that names the technology.
- Record the **line** the project targets (`Node 22 LTS`, `PostgreSQL 17`), not a floating
  `latest`. If a minor or patch matters, say why.
- **Do not write versions from memory.** Check the current release before recording it,
  and if you cannot check, write the version you believe is right and mark it
  `to verify` — an unverified version is an open question, not a decision.
- Note the support horizon where it matters — an LTS ending inside the project's life is
  a decision, not a detail.

**Record each row's status honestly: `decided`, `provisional`, or `open`.** A choice made
in a planning conversation without a developer in the room is `provisional` — write it
down, and tell the user which rows should get a real design discussion before stage 6
hardens anything. `open` rows are not failures; an infrastructure decision the user now
knows they have to make is this stage working, not this stage failing.

Output `05_tech_decisions.md`: a decision table (`Decision | Choice | Status | Why |
Reversal cost`), an ASCII architecture sketch of what was discussed, an infrastructure
checklist showing which items are decided and which are open, and open questions. Spend
the care on the expensive-to-reverse rows; note the cheap ones and move on.

---

## Stage 6 — Scaffolding

Planning that ends in documents leaves the developer with nothing to build in. This
stage turns the five artifacts into a working project.

1. Is this a new repo or an existing one?
2. Which phase does the first build belong to — `SEED` (structure) or `MVP` (prove it works)?
3. Does the team already have a design system to inherit, or does this start one?

Then generate, deriving every file from the artifacts above — never from a template:

| File | Derived from | Contains |
|---|---|---|
| `docs/STACK.md` | stage 5 decision table | every technology with its pinned version and status |
| `docs/SCHEMA.md` | stage 2 features, stage 5 data source | entities, fields, relationships |
| `docs/DATA_PIPELINE.md` | stage 5 | where data enters, how it moves, what owns it |
| `docs/DESIGN_SYSTEM.md` | stage 4 screens | the tokens actually used in `04_screens.html` |
| `docs/PROGRESS.md` | stage 2 | empty phase-level snapshot, ready for `qq`/`cc` |
| `PHASES.md` | stage 2 priorities | first phase from `M` features, later ones from `S`/`C` |
| `CURRENT_PHASE.md` | stage 2 + stage 1 | scope, `Done when` from acceptance criteria, `Do NOT touch` from out-of-scope |
| `CLAUDE.md` | stage 1 principles, stage 5 | project rules an agent must follow here |
| `AGENTS.md` | same | agent-facing entry point if the project uses one |
| `vibe-harness/decisions.json` | stage 5 decision table | each decision as a durable entry |

**`CURRENT_PHASE.md` gets its `Do NOT touch` list from stage 2's out-of-scope section.**
That is the payoff of having kept "not building" and "not decided" separate — only the
former becomes a hard boundary.

Do not invent schema fields the requirements do not call for. An entity with no feature
behind it is a guess, and it will be built.

### Write the file even when the answer is "not yet"

Some projects will not need a data pipeline, or will not have picked a database. **Create
the file anyway**, with a one-line statement of what it is for and `미정 / not yet
decided` where the content would go. A named empty file tells the next person that this
decision exists and is waiting; a missing file tells them nothing, and the decision gets
made by accident later.

Write the stage 5 status through to the scaffolding: `open` rows become explicit "not yet
decided" sections, not silent omissions. A scaffold that looks complete when nine
infrastructure decisions are still open is lying about the project's state.

---

## Finishing

1. List every artifact with its path.
2. Name what is still open — the `[assumption]` rows especially.
3. **Propose** follow-up implementation tasks for the kanban, derived from stage 2's
   must-haves. Show the list and ask before writing them. Do not create tasks
   unprompted. Follow the task field rules in the `vibe-harness` skill.

## Red flags

| Thought | Reality |
|---|---|
| "I'll ask everything up front, then write all the docs" | Later answers depend on earlier documents. Gate by gate. |
| "The product name tells me what it does" | The name is the frame that hides the other half. Ask question 2 twice. |
| "They approved the principle, so it's theirs" | They reviewed your sentence. Ask them to claim it. See the authorship rule. |
| "The principle is clear enough without a test" | A principle you cannot apply in an argument is decoration. |
| "They didn't say who they're *not* for, I'll skip it" | That section is where scope discipline comes from. Ask again. |
| "This role only taps one button, it doesn't need stories" | A role that touches the product needs a screen and a story, or you will not build it. |
| "They only marked must-haves, I'll grade the rest" | Ungraded means ungraded. Write "not yet decided." |
| "I'll estimate the market size to fill the gap" | Unbacked numbers go in open questions marked `[assumption]`. |
| "Wireframes can wait until after implementation starts" | Stage 4 exists because building without seeing the screen is how work gets thrown away. |
| "They didn't mention auth, so it's not needed" | They may not know it is a decision. That is exactly what stage 5 is for. Walk the whole checklist. |
| "I'll list four frameworks and let them pick" | A bare menu is a poll. Explain what each choice does and what breaks, then decide together. |
| "Stack is decided, stage 6 can harden it" | Decided in a room without a developer means `provisional`. Scaffold around it, don't cement it. |
| "The documents are done, planning is finished" | Stage 6 is what makes it a project instead of a folder. |
