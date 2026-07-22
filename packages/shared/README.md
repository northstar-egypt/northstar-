# @northstar/shared

Shared types and per-sport validation schemas. One source of truth for the shapes that cross
the frontend, backend, pipelines, and ML code.

## What is here

```
src/index.ts                        TypeScript core types (consumed by apps/web)
python/northstar_shared/__init__.py Python core types (consumed by apps/api, data, ml)
schemas/football.schema.json        JSON Schema validating football PerformanceEntry.metrics
schemas/table_tennis.schema.json    JSON Schema validating table tennis metrics
```

The core types mirror `docs/schema.md`. The JSON schemas are the per-sport validation for the
`metrics` JSON field, the heart of the shared-core + sport-modules design.

## The sync situation (read this)

Right now the TypeScript and Python core types are **hand-written duplicates**. They must be
kept in sync by hand. This was a deliberate bootstrap choice to avoid overbuilding.

TODO: replace the duplication with codegen from a single source of truth so the two sides
cannot drift. Candidate approaches: generate both from the JSON schemas, or from Pydantic
models. Pick one when the schema stabilizes.

The per-sport JSON schemas, by contrast, are already a single source of truth: both sides
load the same files from `schemas/`.

## Usage

TypeScript (from the web app, via npm workspaces):

```ts
import type { Player, PerformanceEntry } from "@northstar/shared";
```

Python:

```python
from northstar_shared import Player, PerformanceEntry, schema_path
```

TODO: package the Python module so `data/` and `ml/` can import it cleanly (a small
`pyproject.toml` or a path install). For now, add the path to `PYTHONPATH`.
