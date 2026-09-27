---
name: vibe-review
description: Reviews your own work the way a CTO reviews a team member — evidence-based, unsparing, tracking repeated failures across weeks. Weekly scored review, a short daily pass on yesterday's output, and a monthly review left in the project as markdown so later sessions and agents can read it. Use at the start of a day, at the end of a week, at the end of a month, or when you want an outside read on what you have actually shipped.
user-invocable: true
---

# Vibe Review — The Review You Would Give Someone Else

The point is **self-objectivity**: taking the standard you would apply to a team member
and applying it to your own repo. Not a summary, not a morale exercise. A review.

Whether someone can keep reading an outside assessment of their own work, week after
week, is itself the signal. Do not make that easier by being kind.

**Write the review in the language the user works in.** The headings below are English;
mirror them in whatever language the repo and its commits are written in.

## Who is being reviewed

Default: **whoever authored the commits in scope** — usually the person running this.
Get the handle from `git config user.name` / `user.email`, or from the commit authors in
the period. Ask once if it is ambiguous, then keep using it so history accumulates under
one name.

The skill does not need to know whether you are reviewing yourself or a team member. The
evidence rules below are the same either way — what differs is which bias you are
fighting. Reviewing your own work, you know too much and will excuse things. Reviewing
someone else's, you know too little and will guess at intent. **Both are solved by
judging artifacts and running the checks yourself.**

## The bias you are fighting

**You helped write the code you are reviewing.** You know why every shortcut was taken,
which failures were "just a setup issue", and what was going to be fixed next week. A
real outside reviewer knows none of that, and their ignorance is the whole value.

Four rules keep the review honest:

1. **Judge artifacts, not intentions.** Commits, code, tests, docs, and what actually
   runs. **Do not use the conversation as evidence.** If the reasoning is not in the
   repo, it does not exist — that is a finding, not context.
2. **Do not trust any report.** If a document says the tests pass, run them. The single
   most valuable finding this review can produce is *"the report and the HEAD disagree."*
3. **Count AI contribution separately.** Commits you co-authored are not exempt from
   scrutiny; they are a measurement. High AI output with no human verification trail is
   a finding, not a productivity win.
4. **Never soften a repeat.** A problem in its third consecutive week is worse than a new
   one of the same size, and the review must say so in those terms.

## Three modes

| | When | Output | Scores |
|---|---|---|---|
| **Daily** | First session of the day | Screen only, no file | No |
| **Weekly** | End of an ISO week | `docs/developer-reviews/<handle>/YYYY-Www.html` + `history.json` | Yes |
| **Monthly** | End of a multi-week span | Same series: `.../YYYY-Www~Www.html` + `history.json`, plus a baseline document | Yes, same nine |

Scope is **the current repo**. Do not widen it without being asked.

**Daily** compares claims to artifacts. **Weekly** scores a week. **Monthly** is the same
apparatus over a longer span — the same nine axes, the same `history.json`, the same
self-contained HTML in the same directory — plus the one thing a week cannot do:
**reconcile what was delivered against the baseline the previous review set.**

Do not invent a second format or a second scoring system for it. The value of the monthly
review is that its score sits in the same series as the ones before it, so `6 → 4` is
legible at a glance. A parallel document with its own scale would break exactly that.

In practice a team that reviews monthly does not also review every week; the span label
carries whatever the cadence actually was (`2026-W34~W37`). Label the span you reviewed,
not the span you wish you had.

Daily mode is wired into the `ss` (sync & status) ritual in the `vibe-harness` skill, so
it runs at session start without being asked for. **If nothing has landed since the last
pass, say so in one line and stop** — that is what keeps repeated `ss` calls cheap and
removes any need to track when the last review happened.

The output path is a default, not a requirement — if the repo already has a place for
this kind of document, use it and stay consistent. What matters is that all weeks for one
person live in one directory beside one `history.json`, because the review is a series.

**Do not write a review into a public repository.** A review names what is weak, quotes
real numbers, and scores the person who wrote the code. That is exactly the material you
would not paste into a public issue. If the repo is public, write to a path the repo does
not track (`private/reviews/` or similar) and, where the team has somewhere central to
put them, send it there — `scripts/review_sync.py` does that for this project.
Check the repository's visibility before choosing the path, not after.

**Do not assume a stack.** Nothing here depends on a language, framework, or CI system.
Find the project's own checks before running anything (see below), and if the repo has no
tests or no CI at all, that is the review's most important finding — not a reason to skip
the section.

---

## Daily mode

Yesterday's output, read by someone who was not there. Keep it short — this runs every
day, and a long one stops being read.

**Gather:** commits since the previous working session — not literally 24 hours. After a
weekend or a break, cover everything since the last one, and say what period you are
covering. Take the diff, any task records that changed state, and **the actual state of
the test suite right now**. Run it. Do not read a status line and believe it.

**Report, in this order:**

1. **What the repo says you did** — from commits and task records, not from memory.
2. **What does not hold up** — claims that the artifacts do not support. A task marked
   done with no test touching it. A "fixed" that has no commit. A report saying green
   against a suite that is red.
3. **What you left open** — unfinished edits, `TODO`s added yesterday, tasks moved to
   `in_progress` and abandoned.
4. **The one thing to fix first today**, and why that one.

No scores. A single day is too small a sample to grade, and daily scoring turns into
noise you learn to ignore. What a day *can* show is **the gap between what was claimed
and what is there** — that is the whole job of this mode.

If yesterday produced nothing, say that plainly in one line. Do not fill the space.

---

## Weekly mode

The full review. Match the structure below so weeks are comparable.

### Gather evidence first — by running things

Never write a score before you have run the project's own checks. What the commands are
depends on the repo; find them in `package.json` scripts, `Makefile`, CI config, or the
project's docs. At minimum, attempt:

- the test suite, and record the exact counts (`N runs, M assertions, K failures`)
- lint, type check, and a production build
- any security or audit check the project already has configured

**Record the real numbers, including the ones that make the week look bad.** If a command
cannot be run, say which one and why — an unrunnable test suite is itself a finding.

Then collect from git for the week: commit count, additions, deletions, files touched,
how many touched test paths, how many touched migration or delivery config, and how many
were AI co-authored.

### Sweep the open issues — before anything else

If the project tracks work as issues, **open the review by sweeping them**, because a
review that only measures the code cannot see the work that was promised and never
closed. Run the project's own sweep (`scripts/gh_surface.py sweep --repo <OWNER/NAME>`
where that exists, `gh issue list` otherwise) and report three buckets: **this week**,
**14 days or older**, and **no linked PR**.

The last bucket is the sharp one. "No linked PR" does not mean no progress — it means
**no evidence of progress**, and those are different findings. If the work did land and
nobody linked it, the missing link is itself the defect: the next reader sees an open
issue and concludes nothing happened.

**Do not close anything.** Present the stale and overdue ones and ask — close, re-date,
or drop on purpose. Dropping on purpose is a legitimate answer and must be recorded as
one. An agent that closes an issue it did not verify makes the tracker lie, which is the
same failure this review exists to catch.

An issue past its due date that survives **two consecutive reviews** goes to the top of
the lede, whatever else happened. Either the work is genuinely stalled, or the issue is
false — and both are worth more than anything else the review would otherwise say.

> Measured 2026-09-27: one repo carried a Goal issue and four children open for 15 days,
> 9 days past their stated deadline, while **1,156 commits landed without one of them
> referencing an issue**. The rule "every PR closes exactly one issue" was already
> written down. Nothing checked it, so nothing followed it.

### Record what you could and could not observe

Before scoring, state the coverage of each evidence source as
`observed` / `unverified` / `missing`:

| Source | `observed` means |
|---|---|
| `git` | Commit history for the period was readable |
| `tests` | You ran the suite and saw the result |
| `ci` | A pipeline actually executed this week |
| `docs` | Requirements or design docs exist for what shipped |
| `deployment` | Something was actually released and you can point at it |

**A missing source lowers confidence, not the score.** Scoring low because you could not
look is as dishonest as scoring high. Say `unverified` and move on — and note it as a
finding if the gap is the project's own fault.

### Score nine axes, 1–10

| Axis | `history.json` key | What it measures |
|---|---|---|
| Overall | `overall` | The honest single number |
| Requirements | `requirements` | Are they written down and traceable to code |
| Architecture | `architecture` | Boundaries and responsibilities |
| Implementation | `implementation` | Does the hard part actually work |
| Testing | `testing` | Coverage relative to what shipped this week |
| Change management | `git_change_management` | Are commits reviewable and purposeful |
| Operations | `operations` | CI, deploy, migrations, rollback, storage |
| **AI utilization** | `ai_utilization` | How heavily AI tools were used to produce the work |
| **AI supervision** | `ai_supervision` | How much of that output a human actually verified |

**Keep the last two separate.** High utilization with low supervision is the specific
failure mode this catches, and collapsing them into "productivity" hides it.

### Absolute anchors — pick, do not adjust

Score against fixed anchors. **Do not start at 5 and nudge.** Choose the highest anchor
the artifacts actually satisfy.

| | Anchor |
|---|---|
| 1–2 | Broken or unsafe; a critical path fails |
| 3–4 | Materially incomplete; key integration, boundaries, or verification missing |
| 5 | Main path works, with important gaps |
| 6 | Consistent within scope, basic verification present |
| 7 | Traceable, integrated, reviewed, boundaries verified |
| 8 | Operationally ready for its scope; safe to deliver |
| 9 | Complex outcome completed exceptionally; observable and recoverable |
| 10 | Every relevant claim independently verified; raises the team's repeatable standard |

**Overall is not an average.** It has its own gates: 7+ requires traceable integrated
outcomes and verified boundaries; 8+ requires operational readiness for the scope; 9+
requires every critical axis at 7 or above with no unresolved critical risk.

Two rules that keep scores honest:

- **Activity is not evidence.** Commit count, lines changed, files touched, and commit
  message format are for finding things to look at. They are *not* grounds for a score.
  A tidy commit history proves the history is tidy, nothing more.
- **Unverified is not zero.** If you could not establish something, it is unknown — say
  so. Do not score it as absent.

**AI utilization means how much the work was produced using AI tools.** It does not mean
the product contains AI features. Difficulty of building an AI feature belongs to
architecture and implementation, never here.

| Band | AI utilization | AI supervision |
|---|---|---|
| 1–2 | Small explicit assists | Accepted without verification |
| 3–4 | Several limited tasks | Some checking, critical boundaries missed |
| 5–6 | Regular use on major units of work | Main paths verified |
| 7–8 | Central tool across most of the work | Assumptions challenged, boundaries tested, corrections recorded |
| 9–10 | Fully instrumented across planning, building, verifying, iterating | Systematic, adversarial, independently reproducible |

### Every score cites artifacts

For each axis record what moved it, and cite the artifact — a commit, a path, a command
output. **A score you cannot attach an artifact to is an opinion, and opinions are what
this review exists to remove.**

```
testing  score 3  anchor "3–4: materially incomplete"  confidence high
  supports: tests/test_setup_skills.py — install wiring covered by 5 cases
  concerns: skills/ +704 lines this week with 0 tests covering content
  unknowns: no coverage tooling configured, so real coverage is unmeasured
```

Anything in `unknowns` must also appear in `source_coverage` as `unverified`.
Being explicit about what you did not check is the difference between a review and a
verdict.

### Structure of the review

1. **Lede** — one paragraph, the honest headline.
2. **Metrics** — commits, net lines, files touched, overall score.
3. **Change vs last week** — the nine axes side by side with a verdict per row.
4. **What went well** — real, specific, with the artifact that proves it.
5. **What did not** — `P1`, `P2`, … ordered by severity, each with evidence. Mark
   anything carried over from last week as such, with the week count.
6. **Completeness** — which features are done, partial, or missing against the
   requirements, and roughly what stage the product is at.
7. **Next week's completion conditions** — numbered, concrete, verifiable. Not "improve
   testing" but "root CI runs test, lint, build as required checks".
8. **Comprehension checks** — two or three questions that ask you to explain, reproduce,
   or modify something shipped this week, *without looking it up*. In an AI-heavy
   workflow this is the sharpest available probe: code you cannot explain is code you do
   not own, however green the tests are. Write the question and what a passing answer
   would contain.
9. **Verdict** — what can and cannot be trusted to run unattended.
10. **Evidence** — the raw numbers from the commands you ran, and the coverage table.

### `history.json`

Append to `docs/developer-reviews/<handle>/history.json`. **Monthly reviews append here
too** — one series, so the score trend stays readable across whatever cadence the team
actually ran. A span entry carries the span in its label (`"2026-W34~W37"`) and the real
dates in `start`/`end`; nothing else about the entry changes.

```json
{
  "schema_version": 1,
  "developer": { "name": "", "handle": "", "role": "" },
  "reviews": [{
    "period": { "label": "2026-W33", "start": "2026-08-10", "end": "2026-08-16" },
    "scores": { "overall": 6, "requirements": 8, "architecture": 8, "implementation": 7,
                "testing": 5, "git_change_management": 5, "operations": 2,
                "ai_utilization": 9, "ai_supervision": 4 },
    "score_evidence": { "testing": { "anchor": "3-4", "confidence": "high",
                                     "supports": [], "concerns": [], "unknowns": [] } },
    "source_coverage": { "git": "observed", "tests": "observed", "ci": "missing",
                         "docs": "observed", "deployment": "unverified" },
    "verdict": "",
    "priorities": [{ "category": "", "dimension": "testing", "status": "new|repeated",
                     "consecutive_weeks": 1, "severity": "critical|high|medium",
                     "actions": ["measurable action"] }],
    "git": { "commits": 0, "additions": 0, "deletions": 0, "net_lines": 0,
             "files_touched": 0, "test_files_touched": 0,
             "migration_files_touched": 0, "delivery_files_touched": 0,
             "ai_attributed_commits": 0 }
  }]
}
```

### Point the priorities at something

Each `priority` and each `resolved` entry may carry `tasks` and `decisions` — the ids that
addressed the finding:

```json
{ "category": "병렬 세션이 워킹트리를 공유", "severity": "critical",
  "status": "repeated", "consecutive_weeks": 3, "tasks": [78] }
```

**Why this exists.** W36's P1 ran for three weeks and was finally closed by a specific
task, but nothing in the record connected the two — the link lived in whoever remembered
it, and memory ends with the session. A review that names a problem and never points at
its resolution makes the next reviewer re-derive the whole history.

Two rules, both learned by getting them wrong:

- **Only ids you verified exist.** Search the board for the work before writing the id
  (`python3 scripts/search.py <the finding>`). A review that cites a task which is not
  there is a broken link, and a broken link is worse than none — it looks answered.
- **Leave it out rather than guess.** An empty `tasks` is honest; a wrong one is not.
  If the finding was addressed by work you cannot locate, say so in `evidence` instead.

`schema_version` is `2` once any entry uses these fields. Older entries stay valid — the
fields are optional, and nothing backfills them automatically.

Append only. **Read the previous entry before writing the new one** — `status` and
`consecutive_weeks` are the mechanism that makes a stagnant problem impossible to ignore,
and they only work if you carry them forward. A category at three consecutive weeks
should dominate the lede, whatever else happened.

### The HTML

**Start from `references/review-template.html`.** It carries the section order, the markup
classes, and a palette that works in both themes — copy it, replace the placeholders, and
delete the sections this review does not have. Writing the page from scratch each time is
how the layout drifts, and a layout that drifts destroys the comparison the series exists
for.

Self-contained: no CDN, no external fonts, no remote assets, no script. It sits in git and
gets opened months later. Light and dark via `prefers-color-scheme`, readable on a phone —
tables get their own `overflow-x` container so the page body never scrolls sideways.
Keep the layout stable across reviews; the reader is comparing.

Two details in the template are load-bearing rather than decorative. Numbers use
`tabular-nums`, so a column of scores lines up and a changed digit is visible. And the
severity colour lives on the finding's left border, not in its text, so a page of findings
shows its own shape before any of it is read.

---

## Monthly mode

Everything in **Weekly mode** applies — the same evidence-first gathering, the same nine
axes, the same anchors, the same `history.json`, the same self-contained HTML. What
follows is only what changes when the window is a month instead of a week.

### Count the span, not the calendar

The label is the span you actually reviewed (`2026-W34~W37`), with the real dates beside
it. And **the quantitative window starts where the last review stopped counting.** If the
previous review covered through the 11th, commits and line counts start on the 12th — say
so in the subtitle. Two reviews that both count the same fortnight produce a month that
looks twice as productive as it was, and the second one is the easier place to notice.

The narrative window is wider than the quantitative one. Something opened six weeks ago
and still open is this review's problem even though its commits belong to the last one.

### Reconcile against the baseline the last review set

This is the section a week cannot have, and it is the reason to write a monthly review at
all. The previous review ended by setting what this month had to show. Go get that
document and answer it, **week by week**, in a table: what was promised, what is observed,
and a verdict.

Write verdicts in words, not percentages — `met`, `partially met`, `missed`,
`red risk`, `no-go, evidence needed`. A percentage implies a denominator you usually do
not have, and it flattens the difference between four small things done and one large
thing not done.

**Judge by the standard the plan set for itself.** If the baseline defined what counts as
red risk, and the state matches that definition, the review says red risk — in the
baseline's own words. Importing a fresh standard at review time lets the plan off its own
hook.

**If there is no canonical record of what was approved, do not manufacture a rate.** A
draft proposal is not an approved goal. Say the record does not exist, review against what
does, and make the missing record a completion condition. An invented denominator is worse
than an admitted gap, because it survives into the next review as a number.

**If a goal became physically unreachable inside the window, do not roll it over as
though it were still on track.** Prove the no-go, name what blocked it, and set the
shortest honest re-verification schedule.

### Weight the completion conditions

Weekly mode asks for numbered, verifiable conditions. Monthly asks for the same list with
a **percentage weight on each, summing to 100**. A month has room for five things and not
fifteen, and the weights are where you say which one you would keep if you could only keep
one. Unweighted lists get worked top to bottom, which is not the same as being worked in
priority order.

Write the conditions so that **starting does not count as finishing** — "begin five days
of continuous operation" is met by beginning it, and that is usually not what was meant.

### Next month's goals are decided with the person, not for them

This is the half of the monthly review that actually changes what happens next, and it is
the half a reviewer most easily gets wrong — by writing the goals alone and calling the
result a baseline.

**A baseline nobody agreed to is why next month has no record of approved goals.** That
absence is a finding this review already knows how to make; producing it yourself, one
month in advance, is the failure mode to avoid. The reconciliation table at the top of the
next review is only answerable if a human chose what it reconciles against.

So: draft the candidates from evidence, then **ask, one question at a time**, and let the
answers decide. Use `AskUserQuestion` where the harness has it; elsewhere ask one plain
question per message and wait. The conventions are the same ones `vibe-planning` uses,
and for the same reason:

- **One question per message**, at most four options, each with a short description of
  *why the question matters* and what it costs. A month has room for a few outcomes; the
  options must make the trade visible — what gets dropped if this is chosen.
- **Never invent a priority.** If you did not ask whether something is must-have, it has
  none. "Priority not yet decided" is a real answer; a guessed grade is not.
- **Offer the evidence with the question, not after it.** "Carried for the second month,
  blocks installation" belongs in the option, because the person answering did not just
  spend an hour reading the repo and you did.

Ask about the things a month actually turns on, and no more:

1. **What the month is judged by** — the one outcome that decides met or not met.
2. **What to do with the carried-over items** — close them, schedule them, or drop them
   on purpose. Dropping on purpose is a legitimate answer and must be recorded as one.
3. **What gets sacrificed** if the top goal is at risk. Deciding this in advance is worth
   more than any other answer here, because it is the decision nobody makes calmly later.

Then write the agreed goals in **checkable form** — numbers, state transitions, observable
signals. Not "improve monitoring" but "a disconnected database turns a health endpoint red
within one minute, demonstrated once". The next review reads this file and rules on it; a
goal it cannot rule on will be ruled met.

Record the decision in the document: what was chosen, **what was rejected and why**, who
decided, and on what date. The rejected options are the part that saves an argument later,
because next month someone will ask why the obvious thing was not done.

**Do not write the baseline before the answers exist.** If the person is unavailable,
publish the review with the goals section marked as proposed and unapproved, and say so in
the document — an unapproved draft that admits it is one is honest; the same draft
presented as a baseline is the fabricated record this skill exists to prevent.

### The baseline document is the part agents read

The HTML belongs to the series; a person opens it, compares it to the last one, and moves
on. The forward half — next month's milestones, the completion judgment, the go/no-go
conditions — also belongs somewhere an agent will find it **while doing the work**, not at
the next review.

So write that half as markdown in the project's own documents (`docs/team/` or wherever
the project already keeps team documents), and **put one line pointing at it at the top of
`CURRENT_PHASE.md`** — then again wherever the project keeps its agent-facing instructions
(`CLAUDE.md`, `AGENTS.md`, or the docs index). `CURRENT_PHASE.md` comes first because it
is what the session-start hook prints and what `vibe-harness` reads as the scope signal; an
agent that starts from it and finds no pointer does not know the baseline exists, however
well `CLAUDE.md` describes it. A document nothing points at is not a document an agent will
find, and "an agent could read it" is not the same as an agent reading it.

The pointer names the file and nothing more — `This month's goals: docs/team/<PROJECT>_YYYY-MM_BASELINE.md`.
It does not change scope, so it is not a phase transition and does not wait for one; add it
in the same push as the baseline. Update it when next month's baseline lands.

The next monthly review opens by reading that file. That is the loop, and it only closes
if the file is somewhere both a person and an agent will actually land on.

### Name and shape the baseline the same way in every project

Tools read this file too — a notification that the month's goals exist, a dashboard that
lists them — and a tool cannot guess. Two projects reviewed in the same week produced
`SALPIM_MARU_2026-10_BASELINE.md` with a goals table and `2026-10-BASELINE.md` with only
a completion-conditions table; the second was invisible to everything that read the first.
So the name and the one table are fixed, and everything else in the document is yours:

- **Path**: `docs/team/<PROJECT>_YYYY-MM_BASELINE.md`, where `YYYY-MM` is the month the
  goals are **for**, not the month the review was written. A new file each month — never
  overwrite last month's; the next review reconciles against it.
- **The goals table**, under a heading `## Goals and weights` (`## 목표와 가중치` in a
  Korean document), columns in this order:

  ```
  | # | Goal | Weight | Due | Cards |
  |---|---|---:|---|---|
  | G1 | Energy — sample check + on-site install | 30% | 10-25 | 66 · 76 |
  ```

  In a Korean document the headers are exactly `| # | 목표 | 가중치 | 마감 | 카드 |` —
  translate the heading and the columns with these words, not synonyms. A reader keyed on
  `마감` does not find `기한`; that is how one project's deadlines vanished from the
  channel while its goals came through.

  One row per goal, weights summing to 100, and **the goal cell is one line** — what a
  person scanning a channel needs to recognise the goal. The checkable completion
  conditions from "Weight the completion conditions" go in their own section below, one
  subsection per goal id. A table whose goal cell is the full completion condition reads
  as a paragraph in every place it is quoted. `Cards` is optional.
- **Push it with the review.** The HTML, `history.json` and the baseline land on the
  default branch in the same push. A baseline that arrives on a feature branch has not
  been published yet.

### Settle attribution before writing a word

One person often appears as several committers — a work address, a personal address, a
GitHub `noreply` address, a machine that was set up once and never corrected. Resolve
which identities are this person's, **say so in the document**, and say who confirmed it.

Getting this wrong in either direction ruins the review: split identities undercount the
work, and merging someone else's identity in credits or blames the wrong person. If you
cannot confirm an identity, list it as unresolved rather than guessing. Over a month the
error compounds — a whole machine's output can go missing.

### Extra sections, in the weekly order

Keep the weekly structure and insert two things:

- **Goal reconciliation** — the table above, right after "change vs last review", because
  every score below it is read in light of whether the month did what it said it would.
- **Board and codebase shape** in the evidence section — tasks done in the span against
  the board total, production versus test lines and their ratio, migrations, delivery
  config. A month is long enough for these to have moved.

Two habits from the weekly review matter more here, not less:

- **Credit an improvement without over-crediting it.** "The 52 cards closed in this span
  all have completion records; the 24 older empty ones remain" is the true sentence. Drop
  the second clause and the finding disappears from the next review.
- **Put the repeat count in the finding's title**, not in its body. A baseline missed for
  the second consecutive month is a different finding from a new one and must not read the
  same.

### The role verdict

A month is long enough to say something about the role, and short enough that the sentence
must be precise. Separate capability from what actually went wrong: "the problem is not
capability, it is that substitute output was prioritized over the agreed product outcome"
is a judgment someone can act on. "Underperformed" is not.

---

## Red flags

| Thought | Reality |
|---|---|
| "The test failure is just a setup issue" | You know that because you were there. The reviewer is not. Record the failure. |
| "The report says the suite is green" | Run it. This is the finding that justifies the whole review. |
| "I co-wrote this, so I know it's fine" | That is the bias. Judge the artifact. |
| "Same issue as last week, no need to repeat it" | Repeats escalate. Say the week count out loud. |
| "Lots of code shipped, so it was a good week" | Activity is not evidence. It tells you where to look, not what to score. |
| "The commits are clean, so change management is strong" | That proves the history is tidy. Cite what the commits made safe. |
| "AI wrote most of it, that's efficiency" | Utilization without supervision is the failure mode. Score them apart. |
| "The product has AI features, so utilization is high" | Utilization is about tools used to build. Feature difficulty belongs to architecture. |
| "I couldn't check CI, so operations is a 1" | Unverified is not zero. Say `unverified` and score what you saw. |
| "I'll start at 5 and adjust" | Pick the highest anchor the artifacts satisfy. Nudging from the middle hides the reasoning. |
| "A daily score would show the trend" | One day is noise. Daily mode finds claim-versus-reality gaps, not trends. |
| "Every goal was approved, so it was a strong month" | Approval says what shipped. Count what review found after approval. |
| "No record of approved goals, so call it 4 of 5" | An invented denominator outlives the gap it hid. Say the record is missing. |
| "The month's numbers should cover the whole month" | The last review already counted half of it. Start where it stopped. |
| "Carry the unfinished milestone into next month" | If it became unreachable, prove the no-go. Rolling it over hides when it died. |
| "The monthly needs its own format, it's a bigger review" | Then `6 → 4` stops being legible. Same axes, same series, wider span. |
| "It's in `docs/`, so agents will find it" | Nothing points at it. Add the pointer where the project's instructions live. |
| "Starting the five-day run counts as meeting it" | Write conditions that starting cannot satisfy. |
| "I read the whole repo, so I know what next month should be" | You know the candidates. Which one the month is judged by is theirs to choose. |
| "I'll write the baseline now and confirm it later" | Later is the next review, and by then it was never approved. Ask first. |
| "Obviously the carried-over item continues" | Dropping it on purpose is a legitimate answer. Ask, and record the answer. |
| "No need to write down the options they rejected" | That is the part that answers 'why wasn't the obvious thing done' next month. |
| "This is harsh for a self-review" | Being readable is not the goal. Being true is. |
