# Migrations

The live database migrations are **Alembic** migrations under `apps/api/alembic`, because
they are generated from the SQLAlchemy models. Run them from `apps/api`:

```bash
alembic revision --autogenerate -m "create core tables"
alembic upgrade head
```

## What this directory is for

Migration-adjacent material that is not an Alembic revision:

- Raw SQL for things Alembic does not express well (complex indexes, `JSONB` GIN indexes,
  append-only triggers on `AuditLog`, seed SQL).
- Notes and diagrams about schema evolution.

Keep the two in step: if you hand-write SQL here that changes the schema, make sure an
Alembic revision captures it too, so a fresh database built from `alembic upgrade head` is
complete. TODO: first core-tables migration once the ORM models exist.
