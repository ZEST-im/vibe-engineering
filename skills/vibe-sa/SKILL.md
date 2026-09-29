---
name: vibe-sa
description: Solution architecture — turns requirements into one coherent system shape (context, quality targets, build-vs-buy, the few decisions that are expensive to reverse) and decides which of application, data, and technical architecture need deeper work. Use when a project moves from planning to building, when a new subsystem or integration is proposed, when someone asks "how should we build this", or before any change that crosses more than one part of the system.
user-invocable: true
---

# Vibe SA — One Shape for the Whole System

A solution architect answers one question before anyone else answers theirs: **what is the
shape of the whole thing, and which decisions in it are expensive to undo?** Application,
data, and technical architecture are each done well by `vibe-aa`, `vibe-da`, and `vibe-ta`.
Done separately and without this step, they are each locally right and jointly wrong — a
clean module boundary that the data model crosses, a schema the chosen infrastructure
cannot back up in time.

This skill owns the cross-cutting layer and the handoff. It does not do the other three's
work.

**Write every artifact in the language the user works in.** The headings below are
English; mirror them in the user's language.

## Start from what exists — never from a blank page

Read before asking. In this order, and say which you found:

1. `docs/planning/` — `01_philosophy.md` and `02_requirements.md` above all. The north
   star and the out-of-scope list are architecture constraints. If they are missing,
   suggest `/vibe-planning` first; architecture without requirements is guessing with
   diagrams.
2. `docs/planning/05_tech_decisions.md`, `docs/STACK.md`, and `vibe-harness/decisions.json`
   — what is already decided. **Do not silently re-decide.** If you think a recorded
   decision is wrong, say so and ask; a decision reversed without a record is how two
   sessions end up building two systems.
3. **The code, if there is any.** In an existing repo the as-is architecture is whatever
   the code actually does, not what a document says. Derive it from entry points, module
   imports, the schema, and deployment config. The gap between the documented and the
   actual shape is usually the most useful finding this skill produces.

## The five things this skill decides

### 1. System context

Who and what the system talks to: user roles, external systems, data that crosses the
boundary, and in which direction. Draw it as a context diagram (Mermaid or ASCII) with the
system as one box. **Every arrow names what flows and who owns the other end.** An
integration with no owner on the other side is a risk, and it goes in the risk table.

### 2. Quality targets — as scenarios, not adjectives

"Scalable, secure, fast" is not a requirement. Write each quality target as a scenario
with a number:

| Attribute | Scenario | Target | Source |
|---|---|---|---|
| Latency | A user opens the dashboard during peak | p95 under 800 ms | user, stated |
| Availability | The primary DB node fails | service back within 15 min | `[assumption]` |

**Never invent a number.** If the user does not know, propose one with its reasoning, mark
it `[assumption]`, and list it in open questions. An invented target that looks precise is
worse than an honest blank — `vibe-ta` will size infrastructure against it.

Pick the three or four attributes that actually drive this system and say why those. A
table of twelve equally weighted qualities has not made a choice.

### 3. Build, buy, or integrate

For each major capability in the requirements: build it, use a managed service, or
integrate an existing product. Write the trade-off in one line each — cost, lock-in,
control, time. **Default to not building what is not the product's differentiator**, and
say when you are applying that default.

### 4. The expensive decisions

List the decisions that cost the most to reverse later, and rank them by reversal cost.
Typical ones: the primary datastore, tenancy model, identity provider, sync vs async
between major parts, where the system of record for each entity lives, and the
deployment unit (one deployable or several).

Each gets a record through `/vibe-harness decide`, with a `revisit` condition — the
observable event that would make you reopen it. A decision with no revisit condition is
either trivial or unexamined.

### 5. What needs a deeper pass

Decide which specialist skills this system needs, and say why for each one:

| Skill | Run it when |
|---|---|
| `vibe-aa` | More than one module or service, or a team of more than one working in parallel |
| `vibe-da` | More than a handful of entities, data that must be correct over time, data other systems consume, or any personal data |
| `vibe-ta` | Anything deployed beyond a single developer machine |

Small systems legitimately skip some. **Say which were skipped and why** — a skipped pass
nobody decided to skip is just a gap.

## Output

`docs/architecture/00_solution.md`, two pages at most:

1. **Shape in one paragraph** — what the system is, structurally.
2. **Context diagram.**
3. **Quality targets table.**
4. **Build / buy / integrate table.**
5. **Expensive decisions**, ranked, each with its decision-log id.
6. **Risks** — `risk | likelihood | impact | what would reveal it early`.
7. **Handoff** — which of `vibe-aa`, `vibe-da`, `vibe-ta` run next, in what order, and
   the specific questions each must answer.
8. **Open questions** — every `[assumption]` above, with who can answer it.

Default order after this skill: `vibe-da` → `vibe-aa` → `vibe-ta`. Data first because the
model constrains the module boundaries; infrastructure last because it is sized against
the other two. Change the order when the system says otherwise, and say why.

## Working with the user

- **One question at a time.** Use `AskUserQuestion`, at most four options, each saying why
  the question matters.
- **Recommend.** Architecture questions are not polls. State the option you would pick and
  the reason, then let the user overrule.
- **Mark authorship.** Where you drafted a target, a risk, or a boundary the user never
  stated, say so and ask them to confirm it as their own. Approving your sentence is not
  the same as having said it.

## Red flags

| Thought | Reality |
|---|---|
| "Let's go microservices, it scales" | Scaling a team and scaling traffic are different problems. Name which one you have, with a number. |
| "The doc says it's layered" | Read the imports. The code is the architecture; the doc is a claim about it. |
| "The user didn't mention availability" | Not raising it is the symptom. Ask. |
| "I'll put 99.99% as the target" | Invented precision. Ask, or mark `[assumption]` with reasoning. |
| "We'll figure out the data owner later" | Two systems will both think they own it. Decide now or record it as open. |
| "This decision is obvious, no need to log it" | Obvious today, forgotten next month. If it is expensive to reverse, it gets a record. |
| "I'll also sketch the modules and the schema here" | That is `vibe-aa` and `vibe-da`. Name the questions and hand off. |
