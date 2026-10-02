---
name: vibe-architect
description: Run the full architecture pass — solution, application, data, and technical — in order, and score the handoff predictions afterwards. Use when someone asks for "the architecture" of a system rather than one specific view, when onboarding onto an unfamiliar codebase, or before a change large enough that no single pass would see all of it. To run one view only, invoke vibe-sa, vibe-aa, vibe-da, or vibe-ta directly.
user-invocable: true
---

# Vibe Architect — Run all four, then check what the first one got wrong

This skill owns **order and accountability** across `vibe-sa`, `vibe-aa`, `vibe-da`, and
`vibe-ta`. It holds none of their content — each pass keeps its own body, and this file
never restates it.

**Write every artifact in the language the user works in.**

## Run all four. Do not let `vibe-sa` cancel the others.

`vibe-sa` ends with a handoff table saying which deeper passes are needed. **Treat that
table as a prediction to be scored, not as an instruction to skip.** Run all four unless
the user says otherwise.

This default is not a preference. It was measured, once, on 2026-09-29:

| Pass | `vibe-sa` predicted | What the pass actually found |
|---|---|---|
| `vibe-aa` | run it first | correct — static imports hid seven dynamic edges |
| `vibe-da` | skip: "few entities, model already documented" | **wrong** — 17% of rows broke a rule the documentation already stated |
| `vibe-ta` | skip: "never deployed off the developer machine" | **wrong, and worst** — a crash loop had run 95,251 times over 5.5 days, unseen |

**Every skip was justified by "the target is small."** But the system's actual incidents
were never about size — they were about *silence*, which `vibe-sa` had itself written down
two sections earlier and then failed to use.

So: **a skip is only legitimate when the pass is unrelated to how this system actually
gets hurt** — never because the subject looks small. If the user asks to skip one, record
their reason, not yours.

## Order

```
vibe-sa  →  vibe-da  →  vibe-aa  →  vibe-ta
```

Data before application because the model constrains the module boundaries; technical last
because it is sized against the other two. This is `vibe-sa`'s own stated default.

**In an existing repo the order matters much less** — every pass measures the code rather
than deriving from the pass before it, so a different order costs little. Say which order
you used and why. Run one pass at a time; each finishes its artifact before the next
starts.

## After each pass — score the prediction

When a pass finishes, append one row to a **사후 교정 / Post-hoc correction** section in
`docs/architecture/00_solution.md`: what `vibe-sa` predicted for that pass, what the pass
actually found, and whether the prediction held.

This is the point of the wrapper. Without it, a wrong handoff is invisible — the skipped
pass leaves no trace, so nobody learns the skip was wrong. Three or four projects of these
rows are what would justify changing the defaults above, and **a claim about skipping made
without those rows is the same guess this section exists to replace.**

Keep it to a table plus a line or two on *why* a prediction missed. It is a correction, not
a retrospective.

## Output

The four passes write their own artifacts — `00_solution.md`, `01_application.md`,
`02_data.md` + `glossary.md`, `03_technical.md`. This skill adds nothing except the
post-hoc section inside `00_solution.md`.

When all four are done, report in one place:

1. **One line per pass** — the single most expensive finding it produced.
2. **The prediction scoreboard** — how many of `vibe-sa`'s handoff calls held.
3. **What is a check and what is still only a document.** An architecture pass that
   produced only prose has produced a claim. Say plainly which findings were wired into a
   check that fails, and which were not — do not let the document count as the fix.

Then stop. **Do not start implementing the findings.** Each pass ends with open questions
addressed to the user; scope comes from them, not from the momentum of having just
finished four passes.

## Red flags

| Thought | Reality |
|---|---|
| "`vibe-sa` said data was fine, so skip `vibe-da`" | That prediction is what this wrapper exists to test. Run it and score the call. |
| "It's a small system, `vibe-ta` won't find anything" | "Small" was the reasoning behind every wrong skip on record. Ask what makes this system *hurt* instead. |
| "I'll run all four in one go and write it up at the end" | One pass, one artifact, then the next. Four analyses held in mind at once degrade together. |
| "The user only wants the module structure" | Then they want `vibe-aa`. Invoke it directly; this wrapper is for the whole shape. |
| "I've found the problems, let me fix them" | Findings are not a mandate. The open questions go to the user first. |
| "The docs are written, so the architecture pass is done" | A finding that did not become a check is still a claim. Say which ones are which. |
