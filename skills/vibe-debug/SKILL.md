---
name: vibe-debug
description: Find the root cause before changing anything — for a bug, a test failure, a check that went red, or behaviour nobody can explain. Use when the cause is not yet known, when a previous fix did not hold, or when the same symptom has come back.
user-invocable: true
---

# Vibe Debug — Find the cause before you touch anything

The failure this prevents is not "wrong fix". It is **a fix that makes the symptom go
away while the cause stays**, because that one comes back later, bigger, and by then
everybody believes the thing was fixed.

Reach for this when the cause is not yet known. Not every edit needs it — a typo in a
string is a typo in a string. But a bug you can explain in one sentence is one you
already investigated, and a bug you cannot is one where guessing costs more than looking.

## The rule

**No fix before the cause is named.**

You can name it or you cannot. If you cannot, you are still in step 1, whatever the
pressure says. Systematic is not the slow path — it is the path that does not need
redoing.

---

## 1. Find where it breaks

**Read the error completely.** All of it, including the parts that look like noise.
Line numbers, paths, exit codes. An error message is usually the only part of the system
that is telling you the truth without being asked.

**Reproduce it.** Exact steps, every time. If it only sometimes happens, that *is* the
finding — go collect more data rather than fixing on one sample.

> **Emptying the environment is not the same as turning the feature off.**
> This repo reproduced a CI failure with `env -i` and it passed, because macOS git
> *guessed* the identity that CI did not have. `user.useConfigOnly` turned the guessing
> off and the failure appeared. A reproduction that passes may mean the reproduction is
> wrong, not the report.

**Check what changed.** `git log`, `git diff`, new dependencies, a config that moved, a
machine that is not the other machine.

**Instrument the boundaries.** When the system has parts — hook → script → server,
API → service → DB, CI → build → deploy — do not reason about which part is wrong. Print
what enters and what leaves each boundary, run it once, and read where the value stops
being right. One run of evidence beats three rounds of guessing.

**Trace backwards to the source.** Where did the bad value first exist? What produced it?
Keep walking up. The place the error surfaced is rarely the place it was created.

**Verify from outside.** A check that runs inside the thing being checked cannot see the
thing's blind spot. This repo shipped a server that crashed on every start for twelve
days: the function had three tests and they all passed, but **nothing ever started the
process**. The bug lived in the one place no test looked from.

---

## 2. Compare working against broken

Find something similar that works — in this repo, in this file, in the same call path.
Read it completely rather than skimming for the interesting line.

Then list **every** difference. Not the ones that seem important; every one. "That cannot
matter" is a hypothesis, and it is the hypothesis that hides root causes most often.

---

## 3. One hypothesis, one change

Write it as a sentence: **"X is the cause, because Y."** If you cannot finish that
sentence, go back to step 1.

Then test it with **the smallest change that could prove it**. One variable. If you change
three things and the symptom goes, you have learned nothing about which one mattered, and
you now have two unexplained edits in the tree.

If it did not work, form a *new* hypothesis. Do not stack a second fix on the first.

**When you do not know, say so.** "I don't understand why the timestamps don't line up"
is a useful sentence. A confident wrong explanation costs the next person an hour.

---

## 4. Fix the cause

**Write the failing test first.** It must fail for the right reason before you fix
anything, or you will not know whether the fix worked or the test was always green.
Make it reproduce the *symptom*, not your theory of the symptom.

**One fix.** No "while I'm here" cleanups in the same change. When it later turns out the
fix was wrong, you want to revert the fix, not archaeology.

**Then ask the question that this repo learned the hard way:**

> ### Is there another path that does the same thing?
>
> A fix at a real source is still half a fix if a second source exists. This repo closed
> an issue after fixing the startup path that recreated deleted directories — and a
> five-second background loop recreated them too. The issue said COMPLETED for twelve
> days while the bug kept happening, and the person hitting it assumed they were deleting
> wrong.
>
> Before you call it fixed: grep for the other callers. Ask what else writes this, starts
> this, creates this. Two paths doing one job is common, and the second one is exactly
> what a passing test suite will not tell you about.

**Verify by the symptom, not by the commit.** "Fixed" means *the original symptom no
longer reproduces* — run the thing that broke. A commit existing is not evidence; a green
suite that never covered this path is not evidence.

---

## When fixes keep failing

Count them. After the third failed fix, **stop fixing.**

Three failures with a pattern — each fix uncovering shared state somewhere new, each fix
demanding "just a bit of refactoring", each fix breaking something else — is not three
bad hypotheses. It is one wrong structure. Continuing is inertia.

Bring it to your human partner as an architecture question, not a fourth attempt.

---

## Red flags

| Thought | What it means |
|---|---|
| "Quick fix now, investigate later" | Later never comes; the symptom is gone so nobody looks. |
| "Let me just try changing X" | You have no hypothesis. Go write the sentence. |
| "It's probably X" | Probably is not a cause. Trace it. |
| "I'll change these three things and run the tests" | Then you will not know which one worked. |
| "Skip the test, I'll check by hand" | By hand does not run again next week. |
| "I don't fully get it but this seems to work" | Say the first half out loud. That is the finding. |
| "One more fix attempt" (after two) | Stop. Question the structure. |
| "The tests pass, so it's fixed" | Do the tests touch this path? The last one didn't. |
| "The commit is in, so it's fixed" | Reproduce the symptom. That is the only evidence. |
| "It's the obvious place, no need to check the others" | Two paths doing one job is common. Grep. |

## Signals from your human partner that you skipped a step

"Did you read the error?" · "Why is it doing that?" · "Didn't we fix this already?" ·
"Are you guessing?" · "That's the symptom, not the cause."

Each of these means: go back to step 1. They are usually right, and they are saying it
because the answer you gave described *what* you changed rather than *why* it broke.

---

## What this skill does not do

It does not gate your other work. It is a procedure for when the cause is unknown, not a
checklist to recite before every edit — a rule that fires on everything gets switched off,
and then it is there for nothing.

For the fix itself: write the test first, verify before claiming, and keep the change
small. Those are the repo's standing rules, not this skill's.
