# The seed container: brings an empty database up to a state worth looking at.
#
# Built from the repository root rather than from apps/api, because seeding needs three things
# that live in different places: the Alembic migrations (apps/api), the synthetic generator
# (data/pipelines) and the detector run that writes flags (ml).
#
# It runs once on `docker compose up`, then exits. See docker/seed.py for what it does and why
# it refuses to overwrite a database that already has players in it.

FROM python:3.11-slim

WORKDIR /repo

# Build deps for psycopg and friends. Removed in the same layer so they do not ship.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Requirements first, so a code change does not reinstall the world.
COPY apps/api/requirements.txt /repo/apps/api/requirements.txt
COPY data/pipelines/requirements.txt /repo/data/pipelines/requirements.txt

# The pipelines file sources the API's pins with `-r ../../apps/api/requirements.txt`, so the
# two are installed as one environment. Playwright is in there for the ITTF scraper and is not
# used here, but installing the file as written keeps one source of truth for the pins.
RUN pip install --no-cache-dir -r data/pipelines/requirements.txt

COPY apps /repo/apps
COPY data /repo/data
COPY ml /repo/ml
COPY docker/seed.py /repo/docker/seed.py

# apps/api is not an installed package; the generator and the flag writer locate it from the
# repo root, and Alembic is run from inside apps/api.
ENV PYTHONPATH=/repo
ENV PYTHONUNBUFFERED=1

CMD ["python", "/repo/docker/seed.py"]
