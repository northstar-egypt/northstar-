# @northstar/shared

Shared types and the sport modules. One source of truth for the shapes that cross the
frontend, backend, pipelines, and ML code.

## What is here

```
sports/football.json                The football module
sports/table_tennis.json            The table tennis module
src/index.ts                        TypeScript core types (consumed by apps/web)
python/northstar_shared/__init__.py Python core types
```

## Sport modules

A sport is one JSON file in `sports/`. It is the whole of what the platform knows about that
sport, and everything sport-specific reads it:

- **ingest validation** (`apps/api/app/sports.py`, used by the API, the synthetic generator
  and the fraud detector) checks each `PerformanceEntry.metrics` against it
- **the add-player screen** takes the sport list, the role label and the role values from it
  (through `GET /sports`)
- **the player profile** lays out the performance tables and summary statistics from it

Adding a sport means adding a file here. `apps/api/tests/test_sports.py` proves it: it writes
a module for squash, a sport that appears nowhere else in the repository, then adds a player,
records matches and reads the profile, with no code change.

### What a module contains

```jsonc
{
  "sport": "table_tennis",               // the value stored in Player.primary_sport
  "label": "Table tennis",
  "roles": { "label": "Playing style", "values": ["attacker", "all_round", "defender", "chopper"] },
  "usesTier": false,                     // whether the football tier model (pro/youth/diaspora) applies
  "periods": {
    "table_tennis.match.v1": {           // the PerformanceEntry.schema_ref this validates
      "periodType": "match",
      "label": "Matches",
      "schema": { ... },                 // JSON Schema for metrics, see the subset below
      "invariants": [ ... ],             // rules across fields
      "derived": [ ... ]                 // summary statistics for the profile
    }
  }
}
```

**`schema`** is JSON Schema, restricted to a subset the validator fully checks: `type`
(`object` at the top, then `integer`, `number`, `boolean`, `string`), `required`,
`additionalProperties` (must be `false`), `properties`, `minimum`, `maximum`, `enum`, plus the
annotations `title`, `description` and `x-unit`, which label the profile's columns. A module
using anything else is refused when it loads, so a schema can never quietly mean more than
is being checked.

**`invariants`** are the rules JSON Schema cannot express. Four kinds, each generic enough for
more than one sport:

| rule | meaning | example |
| --- | --- | --- |
| `{"lte": [a, b]}` | a <= b | no more goals than shots |
| `{"ifZero": f, "thenZero": [..]}` | if f is 0, every listed field is 0 | no actions in a match not played |
| `{"raceTo": [a, b], "bestOf": f}` | a finished race to `f // 2 + 1` | a best-of-5 table tennis match ends at 3 |
| `{"atLeast": f, "perUnit": u, "value": n}` | f >= n * u | a won set needs 11 points |

**`derived`** statistics are pooled over a player's valid records: a ratio (`numerator` and
`denominator` field lists, optional `scale`, for example 90 for per-90 rates) or a share of
records (`shareWhere: {"gt": [a, b]}`, for example matches won).

### Validation, and what it is not

`validate()` reports everything wrong with a record, including missing and unknown fields.
`impossibilities()` reports only values that cannot be true. The fraud detector uses the second,
because an incomplete import is a data-quality problem and not fraud. Both read the same
module, so ingest and the detector cannot disagree about what an impossible record is.

The validator is standard library only. Swapping in the `jsonschema` package later is a
change to one function in `apps/api/app/sports.py`.

## The core types

The TypeScript and Python core types are **hand-written duplicates** and must be kept in sync
by hand. This was a deliberate bootstrap choice to avoid overbuilding.

TODO: replace the duplication with codegen from a single source of truth so the two sides
cannot drift.

```ts
import type { Player, PerformanceEntry } from "@northstar/shared";
```

```python
from northstar_shared import Player, PerformanceEntry, sport_module_path
```

TODO: package the Python module so `data/` and `ml/` can import it cleanly (a small
`pyproject.toml` or a path install). For now, add the path to `PYTHONPATH`.
