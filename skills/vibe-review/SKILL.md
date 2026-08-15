---
name: vibe-review
description: Reviews your own work the way a CTO reviews a team member — evidence-based, unsparing, tracking repeated failures across weeks. Weekly scored review plus a short daily pass on yesterday's output. Use at the start of a day, at the end of a week, or when you want an outside read on what you have actually shipped.
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

## Two modes

| | When | Output | Scores |
|---|---|---|---|
| **Daily** | First session of the day | Screen only, no file | No |
| **Weekly** | End of an ISO week | `docs/developer-reviews/<handle>/YYYY-Www.html` + `history.json` | Yes |

Scope is **the current repo**. Do not widen it without being asked.

The output path is a default, not a requirement — if the repo already has a place for
this kind of document, use it and stay consistent. What matters is that all weeks for one
person live in one directory beside one `history.json`, because the review is a series.

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
| **AI utilization** | `ai_utilization` | How much was produced with AI |
| **AI supervision** | `ai_supervision` | How much of it a human actually verified |

**Keep the last two separate.** They are the axes that make this review worth running in
an AI-heavy workflow. High utilization with low supervision is the specific failure mode
this catches, and collapsing them into "productivity" hides it.

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
8. **Verdict** — what this person can and cannot be trusted with independently.
9. **Evidence** — the raw numbers from the commands you ran.

### `history.json`

Append to `docs/developer-reviews/<handle>/history.json`:

```json
{
  "schema_version": 1,
  "developer": { "name": "", "handle": "", "role": "" },
  "reviews": [{
    "period": { "label": "2026-W33", "start": "2026-08-10", "end": "2026-08-16" },
    "scores": { "overall": 6, "requirements": 8, "architecture": 8, "implementation": 7,
                "testing": 5, "git_change_management": 5, "operations": 2,
                "ai_utilization": 9, "ai_supervision": 4 },
    "verdict": "",
    "priorities": [{ "category": "", "status": "new|repeated",
                     "consecutive_weeks": 1, "severity": "critical|high|medium" }],
    "git": { "commits": 0, "additions": 0, "deletions": 0, "net_lines": 0,
             "files_touched": 0, "test_files_touched": 0,
             "migration_files_touched": 0, "delivery_files_touched": 0,
             "ai_attributed_commits": 0 }
  }]
}
```

Append only. **Read the previous entry before writing the new one** — `status` and
`consecutive_weeks` are the mechanism that makes a stagnant problem impossible to ignore,
and they only work if you carry them forward. A category at three consecutive weeks
should dominate the lede, whatever else happened.

### The HTML

Self-contained: no CDN, no external fonts, no remote assets. It sits in git and gets
opened months later. Light and dark via `prefers-color-scheme`, readable on a phone.
Keep the layout stable across weeks — the reader is comparing, and a redesign every week
destroys that.

---

## Red flags

| Thought | Reality |
|---|---|
| "The test failure is just a setup issue" | You know that because you were there. The reviewer is not. Record the failure. |
| "The report says the suite is green" | Run it. This is the finding that justifies the whole review. |
| "I co-wrote this, so I know it's fine" | That is the bias. Judge the artifact. |
| "Same issue as last week, no need to repeat it" | Repeats escalate. Say the week count out loud. |
| "Lots of code shipped, so it was a good week" | With no tests touched, that is a finding. Check the ratio. |
| "AI wrote most of it, that's efficiency" | Utilization without supervision is the failure mode. Score them apart. |
| "A daily score would show the trend" | One day is noise. Daily mode finds claim-versus-reality gaps, not trends. |
| "This is harsh for a self-review" | Being readable is not the goal. Being true is. |
