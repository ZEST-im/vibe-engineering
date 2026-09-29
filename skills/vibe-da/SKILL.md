---
name: vibe-da
description: Data architecture — conceptual, logical, and physical data models, a standard glossary of terms and codes, system of record per entity, data flows, sensitivity classification, retention, and migration rules. Use when designing or changing a schema, adding entities, integrating a data source, handling personal data, when the same thing is called three different names in the code, or when vibe-sa hands off data design.
user-invocable: true
---

# Vibe DA — The Part That Is Hardest to Change

Code can be rewritten in an afternoon. Data that has been written wrong for six months
cannot. The database is the hardest thing in a system to migrate, and the vocabulary baked
into it spreads into every API, screen, and report.

Data architecture decides **what the things are, what they are called, who owns each one,
how it moves, and how long it lives** — before the first row is written.

**Write every artifact in the language the user works in.** Glossary terms go in both the
user's language and the identifier used in code.

## Inputs

Read, and say which you found: `docs/architecture/00_solution.md`,
`docs/planning/02_requirements.md`, `docs/SCHEMA.md`, `docs/DATA_PIPELINE.md`, and in an
existing repo **the actual schema and migrations**. The migrations are the truth;
`SCHEMA.md` is a claim. Where they disagree, that is the first finding.

## Build the model in three passes

Each pass is shown to the user and approved before the next. Skipping to tables is how a
physical detail becomes a business rule nobody chose.

### 1. Conceptual — what exists in the business

Entities and relationships in business language only. No types, no keys, no tables. The
user should be able to read it and say "yes, that is how our world works." **Every entity
traces to a requirement.** An entity with no feature behind it is a guess, and it will be
built — leave it out.

### 2. Logical — attributes, keys, rules

Attributes with meaning and constraints, identity (what makes one instance unique in the
business, independent of any surrogate ID), cardinality, and the invariants that must
always hold. Decide here how **time** is modeled: current state only, or history. Anything
regulators, auditors, or disputes will ask about later needs history, and adding it later
means reconstructing the past.

### 3. Physical — how it is stored

Tables or collections, types, indexes for the known access patterns, partitioning if
volumes call for it, and the datastore — which comes from the decision log, not from
here. Name the access patterns you are indexing for; an index with no query behind it is a
write cost with no benefit.

## Standards

### Glossary of terms and codes

One table: `term | code identifier | definition | allowed values | owner`. Every name used
in the schema appears here exactly once. **One concept, one name** — if the code has
`client`, `customer`, and `account` for the same thing, that is a finding, and the
glossary picks one. Code sets (statuses, types, categories) are listed with every allowed
value and what each means.

This is the artifact that pays back most in AI-assisted work: an agent reading the
glossary uses the right name; an agent without it invents a fourth one.

### Naming and type rules

Case convention, singular or plural, how keys and foreign keys are named, how timestamps
and time zones are stored, how money and quantities with units are stored. **Store
timestamps in UTC with the zone made explicit; store money as exact decimal or integer
minor units, never floating point; store units alongside quantities** unless the unit is
fixed by the column's definition.

## Ownership, flow, lifecycle

- **System of record** — exactly one per entity. Every other copy is a replica and says
  where it comes from and how stale it may be. This table feeds `vibe-aa`'s module
  ownership.
- **Data flows** — where data enters (users, devices, uploads, external APIs, batch
  files), how it is validated at the boundary, where it moves, and what consumes it. Draw
  it.
- **Sensitivity** — classify each attribute: public, internal, personal, sensitive
  personal. Personal and sensitive data get: why it is collected, who may read it, how it
  is protected, and when it is deleted. The applicable law comes from the user — ask which
  jurisdictions apply rather than assuming.
- **Retention** — how long each class of data is kept and what happens after: delete,
  anonymize, or archive.

## Migrations

State the migration rules the project follows: every schema change is a versioned
migration in the repo, no manual changes in production, and changes to live tables are
**expand then contract** — add the new shape, migrate reads and writes, backfill, then
remove the old — so no deploy requires downtime or a coordinated release. Each migration
says how it is rolled back, or says explicitly that it cannot be.

## Output

`docs/architecture/02_data.md`, three pages at most, plus the glossary:

1. **As-is findings** (existing repos) — schema vs. docs drift, naming conflicts.
2. **Conceptual diagram.**
3. **Logical model** — entities, identity, invariants, history decisions.
4. **Physical model** — or an update to `docs/SCHEMA.md`, kept as the single physical
   reference.
5. **System of record table.**
6. **Data flow diagram.**
7. **Sensitivity and retention table.**
8. **Migration rules.**

`docs/architecture/glossary.md` — the terms and codes table.

Record the history model, the system-of-record choices, and any denormalization through
`/vibe-harness decide`, each with a `revisit` condition.

## Red flags

| Thought | Reality |
|---|---|
| "Let's just start with the tables" | Physical first means storage details become business rules. Conceptual, then logical. |
| "Add a JSON column for flexibility" | Flexible for the writer, a guessing game for every reader. Model it, or document the shape and who validates it. |
| "We'll add history later" | Later means the past is gone. Decide now for anything auditable. |
| "Both services can write that table" | Two systems of record is zero systems of record. Pick one. |
| "`SCHEMA.md` is up to date" | Read the migrations. |
| "Store it as a float, it's just a price" | Rounding errors in money are bugs you find in reconciliation. Exact types. |
| "It's only an email address" | That is personal data. Classify it, give it a reason and a retention rule. |
| "The agent will pick sensible names" | It will pick different sensible names each session. The glossary decides. |
