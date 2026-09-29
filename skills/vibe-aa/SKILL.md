---
name: vibe-aa
description: Application architecture — module boundaries, dependency direction, API and interface contracts, and the development standards that keep parallel work from colliding, enforced by a check that fails when a boundary is crossed. Use when splitting code into modules or services, when adding a feature that touches several parts, when agents or developers keep editing the same files, when imports start tangling, or when vibe-sa hands off application design.
user-invocable: true
---

# Vibe AA — Boundaries the Code Cannot Cross by Accident

Application architecture decides **what the parts of the code are, what each one is
allowed to know about the others, and how they talk.** In AI-speed development this
matters more, not less: an agent optimizes the task in front of it, and the shortest path
to a working feature usually goes straight through a boundary.

So the deliverable is not a diagram. It is a set of boundaries **and a check that fails
when one is crossed.** A boundary that exists only in a document will be crossed within a
week, by whoever did not read it.

**Write every artifact in the language the user works in.**

## Inputs

Read, and say which you found: `docs/architecture/00_solution.md` (from `vibe-sa`),
`docs/architecture/02_data.md` (from `vibe-da`), `docs/planning/02_requirements.md`, and
the code.

**In an existing repo, map the as-is first.** Build the real dependency graph from
imports — not from folder names — and show it. Cycles, a "utils" module everything
depends on, and UI code importing the database layer are findings. Report them before
proposing anything.

## Decide, in this order

### 1. Deployment unit

**Default: one deployable, organized as a modular monolith.** Split into separate services
only for a reason you can name: a part with a genuinely different scaling or release
cadence, a different team that must ship independently, or a hard isolation requirement.
"It might need to scale" is not a reason — a well-bounded module can be extracted later;
a badly bounded service cannot be merged back cheaply.

### 2. Modules by business capability

Cut modules along what the system *does* (billing, inspections, reporting), not along
technical layers (controllers, services, models). Layer-first structure makes every
feature touch every folder, which is exactly the collision pattern parallel agents hit.

For each module, one line each: **what it owns**, **what it exposes**, **what it may
depend on.** Data ownership comes from `vibe-da` — a module owns the entities it is the
system of record for, and no other module writes them directly.

### 3. Dependency direction

Draw the allowed dependency graph. It must be acyclic. Domain logic depends on nothing
infrastructural; adapters (DB, HTTP, queues, external APIs) depend on the domain, not the
reverse. Say where the framework is allowed to appear and where it is not.

### 4. Contracts between modules

How modules call each other: in-process interface, internal API, or events. For each
contract record the shape, who owns it, and **how it changes without breaking callers** —
versioning, additive-only rules, or deprecation windows. External APIs get the same
treatment plus authentication and error format.

### 5. Standards that affect structure

Only the ones that change how code is shaped: error handling across boundaries, where
validation happens, transaction boundaries, configuration, logging context, and naming of
modules and public interfaces. Formatting and lint rules belong to the linter, not here.

## Enforce it

Pick the enforcement that fits the stack and **wire it into the project's own checks**
(test suite, lint, or CI — whatever already runs):

- an import-boundary rule in the linter or a dedicated tool for the language, or
- a test that walks the imports and fails on a forbidden edge.

Then **prove it fires**: add a deliberate violation, show the check failing, remove it.
A boundary check that has never failed has not been shown to check anything.

Map modules onto the scope system too: a task scoped to one module should list the other
modules in its `Do NOT touch`, so `vibe-harness` blocks the cross-boundary edit at the
moment it happens rather than in review.

## Output

`docs/architecture/01_application.md`, two pages at most:

1. **As-is** (existing repos) — the real dependency graph and its problems.
2. **Deployment unit** — the choice and the reason.
3. **Module table** — `module | owns | exposes | may depend on`.
4. **Dependency diagram** — acyclic, Mermaid or ASCII.
5. **Contracts** — `contract | between | style | owner | change rule`.
6. **Structural standards.**
7. **Enforcement** — which check, where it runs, and the violation used to prove it.
8. **Migration steps** (existing repos) — ordered, each small enough to be one task.

Record the deployment unit and any service split through `/vibe-harness decide`, each
with a `revisit` condition.

## Red flags

| Thought | Reality |
|---|---|
| "Microservices from day one, so it's ready" | Ready for what? Name the scaling or team reason, or stay one deployable. |
| "The folders are named by domain, so it's modular" | Folders are not boundaries. Read the imports. |
| "Put it in common/utils for now" | That module becomes the thing everything depends on. Give it an owner or put it where it is used. |
| "Just this once, call the other module's DB table" | That is how ownership dies. Go through its contract. |
| "The boundary is documented" | Documented is not enforced. Wire the check and show it failing. |
| "The check passes, so boundaries hold" | Has it ever failed? Inject a violation first. |
| "Refactor everything to the new structure in one go" | Big-bang restructures do not land. Order the migration into single-task steps. |
