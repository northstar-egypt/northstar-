# 0001. Shared core with pluggable sport modules

Status: accepted
Date: 2026-07-22

## Context

NorthStar must support multiple sports (football deeply, table tennis as a generalization
proof) and add more later. Football and table tennis share the idea of a player, biometrics,
time-series, and organizations, but their performance metrics have almost nothing in common.
We need a data model that supports both without a rewrite each time a sport is added, because
generalization across sports is an explicit evaluation target and the team has nine people
who should not have to coordinate a migration to onboard a sport.

## Decision

Split the model into a shared relational core and sport-specific JSON modules.

- Player identity, biometrics (`Measurement`), organizations, affiliations, users, consent,
  and audit are shared core, in normal relational tables with real types and constraints.
- Sport-specific performance lives in `PerformanceEntry.metrics`, a `JSONB` column, validated
  on ingest against a per-sport JSON schema stored in `packages/shared`. Each row records
  which sport schema and version validated it (`schema_ref`).

## Consequences

Positive:
- Adding a sport is a config change (a new validation schema plus metric definitions), not a
  database migration.
- The shared core stays clean, indexable, and easy to reason about for access control and
  cross-sport analytics.
- One source of truth for validation shared by frontend, backend, and pipelines.

Negative / trade-offs:
- The database does not enforce the shape of `metrics`. The application and pipeline
  validation layer must. We accept this; `JSONB` still allows indexing hot metrics when needed.
- Cross-sport queries on a specific metric require reaching into JSON, which is less ergonomic
  than a column. Acceptable because such queries are usually within one sport.

## Alternatives considered

- **A column per metric per sport.** Rejected: turns the schema into mostly-null fields, does
  not generalize, and requires a migration per sport.
- **A table per sport.** Rejected: duplicates the shared core, and every cross-cutting
  concern (access control, audit, dedup) would have to handle N shapes.
