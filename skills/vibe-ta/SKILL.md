---
name: vibe-ta
description: Technical architecture — where the system runs, how big it must be (sized with shown arithmetic), environments, redundancy, backup and restore that has actually been tested, network and secrets, observability, and cost. Use when deciding hosting or cloud setup, preparing a first deployment or a pilot-to-rollout step, estimating capacity or monthly cost, setting availability targets, or when vibe-sa hands off infrastructure design.
user-invocable: true
---

# Vibe TA — Infrastructure You Can Show the Math For

Technical architecture decides **where the system runs, how big it has to be, what happens
when a part of it fails, and what it costs** — servers, network, storage, middleware,
cloud services, and the operations around them.

The characteristic failure here is not a wrong choice. It is **a confident number nobody
calculated**: an instance size copied from a tutorial, an availability target no one
checked against the design, a backup that has never been restored. So every number in
this skill's output either shows its arithmetic or is marked `[assumption]`.

**Write every artifact in the language the user works in.**

## Inputs

Read, and say which you found: `docs/architecture/00_solution.md` (quality targets are
the sizing input), `01_application.md` (the deployment units), `02_data.md` (volumes and
retention), `docs/STACK.md`, and in an existing repo **the actual deployment config** —
IaC, container files, CI workflows, environment files. As with the other passes, what is
deployed is the architecture; a diagram of it is a claim.

## Decide, in this order

### 1. Hosting model

Managed platform, containers on a cloud, VMs, or on-premises. **Default to the most
managed option that meets the constraints**, and name the constraint when you depart from
it: data residency, public-sector procurement rules, an existing contract, latency to a
site, or cost at the expected scale. Ask the user which of these apply; do not assume.

### 2. Capacity — sized, not guessed

Work from the quality targets and data volumes to resources, and **show every step**:

```
peak users 2,000 × 20 requests/min ÷ 60      ≈ 670 req/s   [users: stated; rate: assumption]
670 req/s × 50 ms CPU per request            ≈ 34 cores busy
÷ 0.6 target utilization                     ≈ 56 cores → 4 nodes × 16 cores
```

Do the same for storage (rows × row size × growth × retention, plus indexes and backups)
and for anything with a hard limit (connections, API quotas, queue throughput). Mark which
inputs were stated and which assumed. **Say which input the result is most sensitive to**
— that is the one worth measuring before committing.

### 3. Availability and failure

Take the availability target from `vibe-sa` and check the design can meet it. For each
component: what happens when it fails, how it is detected, how it recovers, how long that
takes. Redundancy is chosen per component against the target — not everywhere by default,
because every replica is cost and operational weight.

### 4. Backup and restore

For each datastore: **RPO** (how much data may be lost) and **RTO** (how long recovery may
take), the backup method that meets them, where backups live (not only in the same
account or region), and **when a restore was last tested.** A backup that has never been
restored is a hypothesis. If no restore has been tested, the first operational task is to
test one, and the output says so.

### 5. Environments and release

Which environments exist (local, staging, production at minimum once real users exist),
how close staging is to production, how config and secrets differ per environment, and how
a release reaches production — including how it is rolled back and how database
migrations fit into that (see `vibe-da`).

### 6. Network and security

Public entry points and what sits in front of them, what is private, how services
authenticate to each other, where secrets live (a secret manager, never the repo or plain
environment files committed anywhere), encryption in transit and at rest, and who has
production access. Least privilege for every service account.

### 7. Observability

Logs, metrics, traces, and alerts: what is collected, where, how long it is kept, and
**which alerts wake a person and who that person is.** Tie alerts to the quality-target
scenarios, not to CPU percentages. An alert nobody is assigned to is a log line.

### 8. Cost

Monthly estimate per component at pilot scale and at target scale, with the arithmetic.
Name what cost scales with (users, storage, requests, data egress) so the user can see
whether a pilot can afford to become a rollout.

## Versions

Every technology named carries an explicit version or release line, per the rule in
`vibe-planning` stage 5. **Do not write versions from memory** — check the current
release, or write the version and mark it `to verify`. Note support end dates that fall
inside the project's expected life.

## Output

`docs/architecture/03_technical.md`, three pages at most:

1. **As-is** (existing systems) — what is actually deployed, and drift from docs.
2. **Deployment diagram** — environments, network zones, components.
3. **Capacity sizing** — the arithmetic blocks, with the most sensitive input named.
4. **Failure table** — `component | failure | detection | recovery | time`.
5. **Backup table** — `datastore | RPO | RTO | method | location | last restore test`.
6. **Release and rollback.**
7. **Security summary.**
8. **Observability and alert ownership.**
9. **Cost table** — pilot and target scale.

Update `docs/STACK.md` with anything new, versions included. Record the hosting model and
the redundancy choices through `/vibe-harness decide`, each with a `revisit` condition.

## Red flags

| Thought | Reality |
|---|---|
| "A medium instance should be fine" | Show the arithmetic, or mark it an assumption. |
| "Make everything redundant to be safe" | Redundancy is cost and complexity. Size it to the target, component by component. |
| "Backups run nightly, we're covered" | When was one last restored? Untested is unknown. |
| "Kubernetes, since we might scale" | Name the load that needs it. A managed platform runs most early systems with a fraction of the operations. |
| "Put the key in the env file for now" | For now is how it lands in a repo. Secret manager from the first deploy. |
| "Alert on CPU over 80%" | Alert on what users feel, and name who gets woken. |
| "The deploy diagram shows two regions" | Check the deployed config. The diagram is a claim. |
| "Cost later, once it works" | A pilot that cannot afford rollout is a dead end discovered too late. Estimate now. |
