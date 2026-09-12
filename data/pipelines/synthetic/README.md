# Synthetic data generator

Generates the NorthStar synthetic dataset **and its answer key**. The answer key
is the point: the three detectors (late bloomer, fraud, duplicate) are graded on
precision, recall and F1, and those numbers can only be computed against cases
whose labels are known in advance. This pipeline plants a known set of them and
writes `ground_truth.json` alongside the data.

No real player data, ever. Everything here is fabricated.

## Running it

From the repository root, with the virtual environment active:

```bash
pip install -r data/pipelines/requirements.txt
python -m data.pipelines.synthetic.generate
```

That requirements file pulls in `apps/api/requirements.txt`, which is what this
pipeline needs: the generators build rows as SQLAlchemy models imported from
`apps/api`. So SQLAlchemy, `psycopg` and `pydantic-settings` all arrive with it,
and they are needed even for a JSON-only run, because importing `app.db` reaches
`app.config` and constructs an Engine.

That writes JSON files plus `ground_truth.json` to
`data/pipelines/synthetic/out/`. There is no order to run things in. One command
builds everything, because the generators depend on each other and the
orchestration lives in `dataset.py`.

To load it into Postgres through the ORM instead:

```bash
docker compose up -d db
python -m data.pipelines.synthetic.generate \
    --database-url postgresql+psycopg://northstar:northstar@localhost:5432/northstar \
    --truncate
```

Useful flags:

| flag | what it does |
| --- | --- |
| `--seed N` | Any run with the same seed produces identical data. Default is in `config.py`. |
| `--players N` | Population size. Planted case counts scale with it, so the positive rate stays roughly constant. |
| `--out DIR` | Where the JSON export and `ground_truth.json` go. |
| `--database-url URL` | Also insert into a database through the ORM. |
| `--truncate` | Delete existing rows first. Only with `--database-url`. |
| `--no-json` | Skip the JSON export. `ground_truth.json` is written regardless. |

## Why the output is not committed

The dataset is a deterministic function of the seed, so committing it would just
be committing something anyone can regenerate in three seconds, and a committed
file drifts out of date the moment a generator changes, with no way to tell.
`out/` is gitignored. Everyone runs the bare command, gets byte-identical data
from the default seed, and model scores stay comparable across machines.

If we ever do want a frozen snapshot (for example to pin the numbers in the
thesis), commit it under a dated directory with the seed in the name rather than
overwriting `out/`.

## What the ML track needs

```python
from data.pipelines.synthetic import ground_truth

gt = ground_truth.load("data/pipelines/synthetic/out/ground_truth.json")

player_ids = gt["population"]["player_ids"]
y_true = ground_truth.label_vectors(gt, player_ids)["fraud"]
# y_pred from your detector, aligned to the same player_ids
```

Three label sets, keyed by player id: `late_bloomer`, `fraud`, `duplicate`.
Labelling is closed-world. **Every player not in a label set is a true negative
for that detector**, so recall is a real number rather than a lower bound.

For a duplicate detector scored on pairs rather than players,
`ground_truth.duplicate_pairs(gt)` returns the positive pairs. For a fraud
detector that works row by row, `gt["flagged_performance_entry_ids"]` lists the
performance entries that were planted as implausible.

`gt["cases"]` carries the detail behind each label. It records how many years an
age was understated, how large a late bloomer's height deficit was at 14, which
variations a duplicate cluster differs by. That is what makes error analysis
possible: "we miss the fraud cases understated by under two years" is a more
useful finding than one F1 number.

## What gets planted, and how

The principle throughout is **generate causally, then label**. A planted case is
not an ordinary row with a column nudged; it is a real inconsistency introduced
at the source, so the signals a detector should find appear on their own.

**Age fraud.** The player's body and performance are generated from their true
age, and a younger `date_of_birth` is recorded against them. The biometric
outlier and the dominance over the stated age group are consequences of the lie,
not decorations added on top. A second, cruder class exists too: a few players
carry self-submitted match rows that fail arithmetic. Those rows are the only
inconsistent rows in the dataset, and their ids are in the answer key.

**Late bloomers.** A maturity offset shifts the whole growth curve later. They
are short for their cohort at 13–15, then have a steep spurt and catch up to the
same adult height. Forecasters fit on the flat early series systematically
under-predict them, which is exactly why they are worth labelling.

**Duplicates.** The same human entered twice. The clone shares the original's
biology, so its measurements and performance are consistent with one person. The
two records differ the way real duplicate entries differ: Arabic orthography
(hamza written or dropped, taa marbuta typed as haa, final yaa as alef maqsura),
a dropped grandfather's name, a date of birth off by a few days or with day and
month transposed, different external ids. About a third of the clusters are
already merged (`status="merged"`, `merged_into` set), which is what puts those
values into the data at all; the rest are left unresolved for the detector to
find.

Each planted player carries exactly one label, so the answer key is unambiguous.

## Module map

| file | what it owns |
| --- | --- |
| `config.py` | Every tunable. Population sizes, planted case counts, the default seed. |
| `rng.py` | The single seeded random source. Nothing else calls `random.*`. |
| `growth.py` | Height, weight and sprint as functions of age. |
| `names.py` | Egyptian names. See the note below. |
| `reference.py` | Organizations, positions, country codes, Arabic name variants. |
| `players.py` | Identity and demographics. Tier, minor status and eligibility are derived here. |
| `measurements.py` | The biometric time-series. |
| `performance.py` | Match and season rows, with the consistency invariants. |
| `affiliations.py` | Affiliation history, built so overlaps cannot occur. |
| `accounts.py` | Users, consent, audit log. |
| `planted.py` | The three planted case types. |
| `ground_truth.py` | The answer key, and the helpers that turn it into label vectors. |
| `dataset.py` | Orchestration, in dependency order. |
| `writer.py` | Database insert and JSON export. |
| `orm.py` | Imports the API's SQLAlchemy models. |

## Notes for reviewers

**Rows are built as ORM model instances, not dictionaries.** The JSON export is
derived from those instances by walking the mapper, so the keys in the file are
the model's attribute names by construction. This is what would have caught the
`audit_logs.json` bug: the column is `metadata`, but the Python attribute is
`event_metadata` because `metadata` is reserved on the declarative Base, so
`AuditLog(**row)` used to raise. `writer.verify_round_trip` now re-instantiates
every model from its own serialised row on every run.

**`Faker("ar_EG")` does not fix the names on its own.** Faker's `ar_EG` locale
ships no person provider and silently falls back to `en_US`, which is where
Stephanie West and Todd Smith came from. `ar_AA` has Arabic names but they are
pan-Arab, come with honorifics, and would pollute name matching. So `names.py`
registers a curated Egyptian provider on the seeded Faker instance. Names follow
the given / father / grandfather / family structure, which is also what makes the
duplicate cases realistic.

**Growth is modelled as a value, not a change.** Height is a function of age,
sampled on the measurement date. Growth between two readings therefore scales
with the gap between their dates, and adults sit on the flat part of the curve
and stop growing, with no special case for either.

**Country codes are alpha-2** here, and `apps/web` uses alpha-3. That is a known
inconsistency with a board item against it. Every code the generator emits comes
from `reference.py` and the choice is named in `config.COUNTRY_CODE_STANDARD`, so
the flip is a one-line change when `docs/schema.md` settles it.

## Tests

```bash
pytest data/pipelines/synthetic
```

Each test is named after the property it protects, for example `test_adults_do_not_grow`,
`test_tier_is_consistent_with_age`, `test_minors_consent_requires_a_named_guardian`,
`test_no_overlapping_active_affiliations`, so a failure says which invariant
broke rather than that something changed. The suite also checks that the planted
signals are really present in the data, on the principle that a label asserting a
signal nobody planted is worse than no label at all.
