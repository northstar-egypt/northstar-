# NorthStar data schema (first draft)

This is the data contract for the whole team. It will be iterated on. Treat changes to the
core tables as significant: propose them in a pull request and flag the relevant workstreams.

Status: draft for review before the first team meeting. Field lists are complete enough to
build against, but names and nullability may still change. Anything uncertain is marked
`TODO`.

## The core design decision: shared core + JSON sport modules

Every table below splits into two kinds of data.

- **Shared core.** Player identity, biometrics, time-series measurements, organizations, and
  the people who use the system are the same idea in every sport. These live in normal
  relational columns with real types, constraints, and indexes.
- **Sport-specific performance.** A football shot map and a table tennis rally-length
  distribution have nothing in common. Rather than add a column per sport (which turns the
  schema into a graveyard of mostly-null fields), sport-specific metrics live in a single
  JSON field, `PerformanceEntry.metrics`, validated by a per-sport JSON schema stored in
  `packages/shared`.

### Why

- **Adding a sport is a config change, not a migration.** A new sport ships as a new
  validation schema plus metric definitions. No `ALTER TABLE`, no downtime, no coordination
  across nine people.
- **The core stays clean and queryable.** Joins, indexes, and foreign keys work normally on
  the data that is actually shared, which is most of what the analytics and access-control
  layers care about.
- **Validation is explicit and versioned.** The JSON is not a free-for-all. Each entry
  records which sport schema and version validated it, so we can evolve metrics safely and
  know exactly what shape any historical row is in.

### The trade-off we are accepting

JSON metrics are not enforced by the database. A malformed metrics blob is a bug the
application and pipeline validation layer must catch, not the database. We accept this
because the alternative (a rigid column per metric per sport) does not generalize, and
generalization across sports is an explicit evaluation target. PostgreSQL `JSONB` still lets
us index and query inside the blob when a specific metric becomes hot enough to warrant it.

### Conventions used below

- Primary keys are `UUID` unless noted. UUIDs avoid cross-source id collisions when merging
  data from FootyStats, scrapers, and manual entry.
- Timestamps are `TIMESTAMPTZ`, stored in UTC.
- `created_at` and `updated_at` exist on every table and are omitted from the field lists
  for brevity.
- "FK" means foreign key. "nullable" is called out explicitly; assume `NOT NULL` otherwise.
- Enums are documented as a fixed value set. They can be Postgres enums or a lookup table.
  Draft leaves that as a `TODO` per enum.

---

## Player

The person. Sport-agnostic identity and biometrics. One row per real human. Deduplication
across sources is a data-engineering concern; `Player` is the canonical record a duplicate
resolves to.

| Field                | Type          | Notes                                                             |
| -------------------- | ------------- | ----------------------------------------------------------------- |
| id                   | UUID PK       |                                                                   |
| full_name            | text          | Display name.                                                     |
| known_as             | text, null    | Short or common name.                                             |
| date_of_birth        | date, null    | Drives all age and maturity math. Null when a source hides it.    |
| sex                  | enum, null    | `male` / `female`. TODO confirm value set.                        |
| nationality          | text[]        | ISO country codes. Array because diaspora players are dual.       |
| is_egypt_eligible    | boolean       | Core to the diaspora tier. Derived or manually set.               |
| primary_sport        | enum          | `football` / `table_tennis`. Extensible. See sport modules.       |
| tier                 | enum, null    | `pro` / `youth` / `diaspora`. Football tiers; null for others.    |
| position             | text, null    | Sport-specific role, for example `ST`. TODO: move to JSON? See note. |
| is_minor             | boolean       | Derived from date_of_birth. Gates privacy safeguards.             |
| external_ids         | JSONB         | Source ids, for example `{"footystats": 123, "transfermarkt": "x"}`. |
| status               | enum          | `active` / `archived` / `merged`. `merged` points via merged_into. |
| merged_into          | UUID FK, null | Self-reference. Set when this record was merged into another.     |

Notes:
- `position` is borderline. It is close to sport-specific, but so central to football
  analytics (age curves are per position) that a first-class nullable column is pragmatic.
  Open question for the first meeting. It may become a typed field inside the sport module.
- Biometrics that change over time (height, weight) are NOT here. They are `Measurement`
  rows, because tracking them over time is the point.

## Organization

Any club, academy, national team, or federation. Self-referencing so an academy can belong
to a club and a club can sit under a federation.

| Field           | Type          | Notes                                                        |
| --------------- | ------------- | ------------------------------------------------------------ |
| id              | UUID PK       |                                                              |
| name            | text          |                                                              |
| type            | enum          | `club` / `academy` / `national_team` / `federation`.         |
| sport           | enum, null    | Null for multi-sport bodies.                                 |
| country         | text          | ISO country code.                                            |
| parent_org_id   | UUID FK, null | Self-reference for hierarchy.                                |
| external_ids    | JSONB         | Source ids.                                                  |

## PlayerOrganization

The many-to-many link between players and organizations over time. A player can move
between academies and clubs; this table is the history of those affiliations.

| Field            | Type          | Notes                                                        |
| ---------------- | ------------- | ------------------------------------------------------------ |
| id               | UUID PK       |                                                              |
| player_id        | UUID FK       | To Player.                                                   |
| organization_id  | UUID FK       | To Organization.                                             |
| role             | enum          | `player` / `youth_prospect` / `trialist`. TODO value set.    |
| start_date       | date          |                                                              |
| end_date         | date, null    | Null means current.                                          |
| shirt_number     | int, null     |                                                              |

Constraint: no two overlapping active affiliations of the same role for one player at one
org. TODO: exact constraint.

## Measurement

Time-series of things we measure directly about a player: biometrics and physical tests.
Sport-agnostic and long-format (one row per player per metric per date), which makes growth
curves and maturity math straightforward.

| Field          | Type          | Notes                                                          |
| -------------- | ------------- | -------------------------------------------------------------- |
| id             | UUID PK       |                                                                |
| player_id      | UUID FK       | To Player.                                                     |
| measured_at    | date          | When the measurement was taken.                                |
| metric         | enum/text     | `height_cm` / `weight_kg` / `sprint_10m_s` / etc. Controlled.  |
| value          | numeric       |                                                                |
| unit           | text          | Stored explicitly to avoid ambiguity.                          |
| source         | enum          | `coach_logged` / `self_submitted` / `import` / `api`.          |
| recorded_by    | UUID FK, null | To User, when a human entered it. Null for automated ingest.   |
| confidence     | enum, null    | `measured` / `estimated`. Maturity models care about this.     |

Why long-format and not wide columns: sports and academies measure different things, and we
want to add a new physical test without a migration. Same philosophy as the JSON metrics,
applied to structured numeric time-series.

## PerformanceEntry

Sport-specific performance for a period (a match, a session, a tournament, or an aggregate
window). This is where the JSON sport module lives.

| Field            | Type          | Notes                                                          |
| ---------------- | ------------- | -------------------------------------------------------------- |
| id               | UUID PK       |                                                                |
| player_id        | UUID FK       | To Player.                                                     |
| sport            | enum          | Which sport's schema validates `metrics`.                      |
| period_type      | enum          | `match` / `session` / `tournament` / `season_aggregate`.       |
| period_start     | date          |                                                                |
| period_end       | date, null    | Null for a point-in-time event.                                |
| organization_id  | UUID FK, null | The club/academy context, if any.                              |
| opponent_org_id  | UUID FK, null | For match-type entries.                                        |
| metrics          | JSONB         | Sport-specific payload. Validated against schema_ref.          |
| schema_ref       | text          | Which sport schema + version validated this, e.g. `football@1`. |
| source           | enum          | `api` / `scrape` / `coach_logged` / `self_submitted` / `import`. |
| is_validated     | boolean       | Did it pass the sport schema validation on ingest.             |

Example `metrics` for football (illustrative, not final):

```json
{
  "minutes": 90,
  "goals": 1,
  "assists": 0,
  "xg": 0.42,
  "shots": 3,
  "passes_completed": 41,
  "distance_km": 10.8
}
```

Example `metrics` for table tennis (illustrative, not final):

```json
{
  "matches_played": 5,
  "matches_won": 4,
  "sets_won": 13,
  "sets_lost": 6,
  "avg_rally_length": 4.2,
  "service_points_won_pct": 0.61
}
```

The per-sport JSON schemas that validate these payloads live in `packages/shared` so the
frontend, backend, and pipelines all validate against one source of truth.

## User

An account that logs into the platform. Distinct from Player: a player may or may not have a
user account, and most users (coaches, scouts, federation staff) are not players.

| Field            | Type          | Notes                                                          |
| ---------------- | ------------- | -------------------------------------------------------------- |
| id               | UUID PK       |                                                                |
| email            | citext        | Unique. Case-insensitive.                                      |
| password_hash    | text          | Hashed only. Never store plaintext. TODO: hashing choice.      |
| full_name        | text          |                                                                |
| role             | enum          | `coach` / `scout` / `federation` / `player` / `admin`.         |
| organization_id  | UUID FK, null | The org this user belongs to. Scopes what they can see.        |
| linked_player_id | UUID FK, null | Set when the user is also a player (self-submission, profile). |
| is_active        | boolean       |                                                                |
| last_login_at    | timestamptz, null |                                                            |

Role is the anchor of the access-control workstream. Draft role intent:
- **coach**: log and edit players within their academy/club.
- **scout**: search and view across scope; cannot edit player records.
- **federation**: oversight and review dashboards; broad read, review actions.
- **player**: view and manage their own profile and self-submissions.
- **admin**: system administration. TODO: confirm this role belongs here vs a separate flag.

## Consent

Consent and privacy records, first-class because much of the youth data is about minors.
One player can have multiple consent records over time and per purpose.

| Field              | Type          | Notes                                                        |
| ------------------ | ------------- | ------------------------------------------------------------ |
| id                 | UUID PK       |                                                              |
| player_id          | UUID FK       | To Player.                                                   |
| purpose            | enum          | `data_storage` / `analytics` / `scouting_visibility` / etc.  |
| granted            | boolean       | Current state for this purpose.                              |
| granted_by         | text          | Who consented: the player, or a guardian for a minor.        |
| guardian_name      | text, null    | Required when the player is a minor. TODO enforce.           |
| valid_from         | date          |                                                              |
| valid_until        | date, null    | Null means open-ended.                                       |
| document_ref       | text, null    | Pointer to a stored consent document, if any.                |

The application must check relevant consent before exposing a minor's profile to scouts.
That enforcement is an access-control concern; this table is the record it reads.

## AuditLog

Append-only record of who did what. Feeds both the security workstream (accountability) and
the integrity board (surfacing suspicious activity). Never updated or deleted.

| Field          | Type          | Notes                                                           |
| -------------- | ------------- | --------------------------------------------------------------- |
| id             | UUID PK       |                                                                 |
| actor_user_id  | UUID FK, null | Who did it. Null for system actions.                            |
| action         | text          | For example `player.update`, `login.success`, `search.run`.     |
| entity_type    | text, null    | For example `Player`, `PerformanceEntry`.                       |
| entity_id      | UUID, null    | The affected row.                                               |
| metadata       | JSONB, null   | Before/after diff, request context, flags raised.               |
| ip_address     | inet, null    |                                                                 |
| created_at     | timestamptz   | Indexed. This is the query axis.                                |

Append-only is a rule, not a suggestion. No `UPDATE` or `DELETE`. TODO: enforce with
permissions or a trigger.

---

## Relationship overview

```
User ----< AuditLog
User >---- Organization
User ----- Player            (optional link via linked_player_id)

Organization --< Organization        (parent hierarchy)
Player --< PlayerOrganization >-- Organization
Player --< Measurement
Player --< PerformanceEntry >-- Organization   (context and opponent)
Player --< Consent
Player --- Player            (merged_into self-reference for dedup)
```

`--<` means one-to-many, `>--` the many side, `---` a link.

## Open questions for the first meeting

- Is `position` a core column or part of the football sport module?
- Password hashing and auth library (security workstream owns this; not decided tonight).
- Exact enum value sets, and enum type vs lookup table for each.
- Do we need a separate `Match` / `Fixture` entity, or is `PerformanceEntry` with
  `opponent_org_id` enough for now?
- Embedding storage for player similarity: a `pgvector` column on Player, or a separate
  table. TODO once the ML workstream picks an embedding model.
