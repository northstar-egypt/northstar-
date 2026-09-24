"""Run the detectors and write what they find into the flag table.

    python -m ml.write_flags
    python -m ml.write_flags --database-url postgresql+psycopg://... --dry-run

This is the batch job that connects `ml/detectors` to the application. Until it runs, the
integrity board is empty and the player profile's flag banner never appears, because the API
reads flags from a table rather than computing them per request (see
`apps/api/app/services/flags.py` for why).

Where the input comes from
--------------------------
The detectors read the JSON export produced by `data.pipelines.synthetic.generate`, and the
flags are written to the database. Those two have to describe the same population, which they
do because the generator writes both from one run with the same player ids. Running this
against a database loaded from a different seed would attach flags to the wrong people, so the
job checks that the player ids it is about to write actually exist and refuses rather than
inserting orphans.

    TODO(ml): a database-backed FeatureSet, so this reads the same rows the API serves instead
    of relying on an export being in step. That is the right shape once there is real ingest,
    and it is not worth building while the only source is a generator that writes both.

Reruns
------
Safe to run repeatedly. Every flag carries a `dedupe_key`, so a case already raised is
recognised rather than duplicated, and a case a reviewer already dismissed is not raised
again. See `make_dedupe_key` in the API's flag service for what the key does and does not
cover.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_DATA_DIR = Path("data/pipelines/synthetic/out")
DEFAULT_DATABASE_URL = "postgresql+psycopg://northstar:northstar@localhost:5432/northstar"

# Bumped when a detector's behaviour changes. Stored on every flag, because a score computed
# six months from now has to be able to say which model produced the flags it is scoring.
DETECTOR_VERSION = "v1"


def _bootstrap_api_path() -> None:
    """Put `apps/api` on the path so the ORM models can be imported.

    Same approach as `data/pipelines/synthetic/orm.py`: apps/api is not an installed package,
    so it is located from the repo root. Importing `app.db` constructs an Engine but opens no
    connection, so this is safe with no database running.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "apps" / "api").is_dir() and (parent / "ml").is_dir():
            api_dir = parent / "apps" / "api"
            if str(api_dir) not in sys.path:
                sys.path.insert(0, str(api_dir))
            return
    raise RuntimeError(f"Could not locate the repository root from {here}.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="write_flags",
        description="Run the detectors and write their findings to the flag table.",
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--database-url", default=DEFAULT_DATABASE_URL)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be written and roll back.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not (args.data_dir / "players.json").exists():
        print(
            f"No dataset at {args.data_dir}. Generate one first:\n"
            f"  python -m data.pipelines.synthetic.generate",
            file=sys.stderr,
        )
        return 1

    _bootstrap_api_path()

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from app.models.enums import FlagType
    from app.models.player import Player
    from app.services import flags as flag_service

    from ml.detectors import duplicate, fraud, late_bloomer
    from ml.detectors.features import FeatureSet

    features = FeatureSet(args.data_dir)

    engine = create_engine(args.database_url, future=True)
    written = {"created": 0, "existing": 0, "skipped": 0}

    with Session(engine) as session:
        known = {
            str(player_id)
            for player_id in session.execute(select(Player.id)).scalars()
        }
        if not known:
            print(
                "The database has no players. Load the dataset first:\n"
                "  python -m data.pipelines.synthetic.generate --database-url ... --truncate",
                file=sys.stderr,
            )
            return 1

        overlap = len(known & set(features.players))
        if overlap == 0:
            print(
                f"None of the {len(features.players)} players in {args.data_dir} exist in the "
                f"database. The export and the database are from different runs; regenerate "
                f"one of them rather than writing flags onto the wrong people.",
                file=sys.stderr,
            )
            return 1
        print(f"{overlap} of {len(features.players)} exported players found in the database")

        def raise_flag(player_id: str, **kwargs) -> None:
            if player_id not in known:
                written["skipped"] += 1
                return
            _, created = flag_service.upsert(
                session,
                player_id=player_id,
                detector_name=kwargs.pop("detector_name"),
                detector_version=DETECTOR_VERSION,
                **kwargs,
            )
            written["created" if created else "existing"] += 1

        # Late bloomer. One case per player: the claim is about the player, not about an
        # event, so the fingerprint is empty and a rerun recognises the same case.
        for player_id, reason in late_bloomer.detect(features).items():
            pf = features.players[player_id]
            raise_flag(
                player_id,
                flag_type=FlagType.LATE_BLOOMER.value,
                reason=reason,
                evidence={
                    "points": [
                        f"Height {pf.height_z_mean:+.2f} SD from the median for age "
                        f"{pf.stated_age:.0f}",
                        f"Growing {pf.recent_velocity:.1f} cm/year over the last year",
                        f"{len(pf.heights)} height measurements on record",
                    ]
                },
                detector_name="late_bloomer",
            )

        # Fraud. The two rules are separate cases with separate evidence, because one is a
        # statistical claim and the other is arithmetic, and a reviewer treats them
        # differently. The fingerprint keeps them apart.
        for player_id, reason in fraud.detect_age_misrepresentation(features).items():
            pf = features.players[player_id]
            raise_flag(
                player_id,
                flag_type=FlagType.FRAUD.value,
                reason=reason,
                fingerprint="age_misrepresentation",
                evidence={
                    "points": [
                        f"Height {pf.height_z_mean:+.2f} SD from the median for the recorded "
                        f"age of {pf.stated_age:.0f}",
                        (
                            f"Growth rate {pf.velocity_z:+.2f} SD against that age group"
                            if pf.velocity_z is not None
                            else "No usable growth rate, this rests on size alone"
                        ),
                        "Body and recorded date of birth disagree",
                    ]
                },
                detector_name="fraud.age_misrepresentation",
            )

        for player_id, reason in fraud.detect_impossible_metrics(features).items():
            pf = features.players[player_id]
            rows = fraud.impossible_rows(pf)
            raise_flag(
                player_id,
                flag_type=FlagType.FRAUD.value,
                reason=reason,
                # The offending rows are the case. A different set of bad rows is a different
                # case and should be raised even if an earlier one was dismissed.
                fingerprint="impossible:" + ",".join(sorted(entry_id for entry_id, _ in rows)),
                evidence={
                    "points": [
                        f"{len(rows)} performance rows break arithmetic",
                        *sorted({description for _, description in rows}),
                        "All self-submitted and unvalidated",
                    ]
                },
                detector_name="fraud.impossible_metrics",
            )

        # Duplicates. Written once per pair rather than once per record, with the partner on
        # `related_player_id` so the integrity board can render the field-by-field diff.
        for (a, b), reason in duplicate.detect_pairs(features).items():
            raise_flag(
                a,
                flag_type=FlagType.DUPLICATE.value,
                reason=reason,
                # Both directions of the same pair are one case.
                fingerprint="pair:" + "|".join(sorted((a, b))),
                evidence={
                    "points": [
                        "Names match after normalising Arabic spelling",
                        "Dates of birth are the same or a few days apart",
                        "Same sex and sport",
                    ]
                },
                related_player_id=b,
                detector_name="duplicate",
            )

        dropped = flag_service.purge_merged_player_flags(session)

        if args.dry_run:
            session.rollback()
            print("dry run, rolled back")
        else:
            session.commit()

    print(
        f"flags raised {written['created']}, already present {written['existing']}, "
        f"skipped (not in database) {written['skipped']}, "
        f"closed against merged records {dropped}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
