"""Creating players and logging measurements.

Who may write is decided in `app.services.access`. This module decides what may be written,
and splits that into two kinds of problem, because the add player wireframe insists on the
difference (`docs/wireframes/03-add-edit-player.html`, "Validation is a question, never a
block"):

  Errors     the reading cannot be true or cannot be stored. A date in the future, a
             measurement taken before the player was born, a metric nobody defined, a weight
             in centimetres. Refused with 422, nothing saved.

  Warnings   the reading is surprising but could be real. A 12 cm jump in four months, a
             height that dropped. Sent back as a question with 409 and nothing saved, until the
             coach resends with `acknowledge_warnings`. Then it is saved, and the audit log
             records that a named person confirmed it.

The warnings are the interesting half. An implausible growth spurt is exactly the
observation the late bloomer and anomaly detectors need, so refusing it would throw away the
signal, and saving it silently would hide a typo among real data. Asking is the only option
that keeps both.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app import sports
from app.models.consent import Consent
from app.models.enums import (
    ConsentPurpose,
    MeasurementSource,
    PlayerOrganizationRole,
    PlayerStatus,
)
from app.models.measurement import Measurement
from app.models.organization import Organization
from app.models.player import Player
from app.models.player_organization import PlayerOrganization
from app.schemas.writes import MeasurementBatchIn, PlayerCreateIn


@dataclass(frozen=True)
class MetricSpec:
    unit: str
    # A reading outside this range is a question, not an error.
    plausible_low: float
    plausible_high: float


# The controlled vocabulary for Measurement.metric (`docs/schema.md`), with the units the
# generator writes. A new physical test is a new line here, not a migration. The ranges are
# deliberately wide: they exist to catch a slipped decimal point or a height typed into the
# weight box, not to judge a child.
METRICS: dict[str, MetricSpec] = {
    "height_cm": MetricSpec(unit="cm", plausible_low=100, plausible_high=220),
    "weight_kg": MetricSpec(unit="kg", plausible_low=20, plausible_high=150),
    "sprint_10m_s": MetricSpec(unit="s", plausible_low=1.4, plausible_high=3.5),
}

# Peak adolescent growth is around 10 cm a year, so 2.5 cm a month is already a fast spurt
# sustained. Matches the ceiling the add player screen uses on the client.
MAX_HEIGHT_GAIN_CM_PER_MONTH = 2.5
# Measuring error on a wall chart is about a centimetre either way. Anything more than that
# downwards is a typo or a different stadiometer, and either way worth a look.
MAX_HEIGHT_DROP_CM = 1.5

# Hard bounds on a date of birth. Outside these it is a typo, not an unusual player.
MIN_AGE_YEARS = 5
MAX_AGE_YEARS = 60


class WriteRejected(Exception):
    """Refused outright. Carries one message per problem so the screen can show them all."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


class NeedsConfirmation(Exception):
    """Surprising but possibly real. Nothing was saved; the caller may confirm and resend."""

    def __init__(self, warnings: list[dict]):
        super().__init__(f"{len(warnings)} reading(s) need confirming")
        self.warnings = warnings


def is_minor_on(dob: date, on: date) -> bool:
    """Under 18 on `on`, by calendar birthday rather than by dividing days.

    The day-count shortcut is off by a day either side of a birthday, and the day a child
    turns 18 is exactly the day this has to be right.
    """
    had_birthday = (on.month, on.day) >= (dob.month, dob.day)
    age = on.year - dob.year - (0 if had_birthday else 1)
    return age < 18


def _years_between(earlier: date, later: date) -> int:
    had_birthday = (later.month, later.day) >= (earlier.month, earlier.day)
    return later.year - earlier.year - (0 if had_birthday else 1)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def check_player(payload: PlayerCreateIn, today: date) -> list[str]:
    problems: list[str] = []
    dob = payload.date_of_birth
    if dob > today:
        problems.append("Date of birth is in the future.")
    else:
        age = _years_between(dob, today)
        if age < MIN_AGE_YEARS:
            problems.append(f"Date of birth makes this player {age}, under {MIN_AGE_YEARS}.")
        elif age > MAX_AGE_YEARS:
            problems.append(f"Date of birth makes this player {age}, over {MAX_AGE_YEARS}.")

    # Joining the platform means signing the consent form, so there is no player without it.
    # A child cannot sign for themselves: the form must name the guardian who did.
    if not payload.consent.signed:
        problems.append("The sign-up consent form has not been signed.")
    elif dob <= today and is_minor_on(dob, today) and not payload.consent.guardian_name:
        problems.append(
            "This player is a minor, so the consent form must be signed by a named guardian."
        )

    # Whether tiers apply, and what a player's role can be, is the sport module's call. A
    # table tennis player with a football tier would be counted in football tier totals on
    # the oversight screen, and a "ST" chopper is a typo nobody would catch later.
    module = sports.registry()[payload.primary_sport]
    # The sport module says which genders it registers. Boys and girls are only ever compared
    # separately, so a sport open to both needs to know which one this player is.
    if payload.sex is not None and payload.sex not in module.genders:
        problems.append(
            f"{module.label} on NorthStar registers {' and '.join(module.genders)} players only."
        )
    elif payload.sex is None and len(module.genders) > 1:
        problems.append(
            f"Gender is required for {module.label.lower()}: boys and girls are compared "
            f"separately."
        )
    if payload.tier is not None and not module.uses_tier:
        problems.append(f"Tier does not apply to {module.label.lower()}.")
    if payload.position is not None and payload.position not in module.roles:
        problems.append(
            f"{payload.position!r} is not a {module.role_label.lower()} in "
            f"{module.label.lower()}. Expected one of: {', '.join(module.roles)}."
        )
    return problems


def check_measurements(
    batch: MeasurementBatchIn, dob: date | None, today: date
) -> list[str]:
    problems: list[str] = []
    if batch.measured_at > today:
        problems.append("Measurement date is in the future.")
    if dob is not None and batch.measured_at < dob:
        problems.append("Measurement date is before the player was born.")

    seen: set[str] = set()
    for item in batch.metrics:
        spec = METRICS.get(item.metric)
        if spec is None:
            problems.append(
                f"Unknown metric {item.metric!r}. Known metrics: {', '.join(sorted(METRICS))}."
            )
            continue
        if item.unit != spec.unit:
            problems.append(f"{item.metric} is recorded in {spec.unit}, not {item.unit!r}.")
        if item.value <= 0:
            problems.append(f"{item.metric} must be greater than zero.")
        if item.metric in seen:
            problems.append(f"{item.metric} appears twice in one visit.")
        seen.add(item.metric)
    return problems


def _previous_reading(
    db: Session, player_id: uuid.UUID, metric: str, on_or_before: date
) -> Measurement | None:
    return db.execute(
        select(Measurement)
        .where(Measurement.player_id == player_id)
        .where(Measurement.metric == metric)
        .where(Measurement.measured_at <= on_or_before)
        .order_by(Measurement.measured_at.desc(), Measurement.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def plausibility_warnings(
    db: Session, player_id: uuid.UUID | None, batch: MeasurementBatchIn
) -> list[dict]:
    """Readings a human should confirm. Empty when everything looks ordinary."""
    warnings: list[dict] = []
    for item in batch.metrics:
        spec = METRICS[item.metric]
        if not spec.plausible_low <= item.value <= spec.plausible_high:
            warnings.append(
                {
                    "metric": item.metric,
                    "value": item.value,
                    "message": (
                        f"{item.value:g} {spec.unit} is outside the usual range for "
                        f"{item.metric} ({spec.plausible_low:g} to {spec.plausible_high:g})."
                    ),
                }
            )
            continue

        if item.metric != "height_cm" or player_id is None:
            continue

        previous = _previous_reading(db, player_id, item.metric, batch.measured_at)
        if previous is None:
            continue
        change = item.value - float(previous.value)
        days = (batch.measured_at - previous.measured_at).days
        if change < -MAX_HEIGHT_DROP_CM:
            warnings.append(
                {
                    "metric": item.metric,
                    "value": item.value,
                    "message": (
                        f"{-change:.1f} cm shorter than the {float(previous.value):g} cm "
                        f"recorded on {previous.measured_at.isoformat()}."
                    ),
                }
            )
        else:
            # Anything under a month is judged as a month, so two readings on consecutive
            # days are allowed the usual measuring wobble and not a 30x growth rate.
            months = max(days / 30.44, 1.0)
            if change > MAX_HEIGHT_GAIN_CM_PER_MONTH * months:
                warnings.append(
                    {
                        "metric": item.metric,
                        "value": item.value,
                        "message": (
                            f"{change:.1f} cm taller than the {float(previous.value):g} cm "
                            f"recorded {days} days earlier, faster than "
                            f"{MAX_HEIGHT_GAIN_CM_PER_MONTH:g} cm a month."
                        ),
                    }
                )
    return warnings


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def _add_measurements(
    db: Session,
    *,
    player_id: uuid.UUID,
    batch: MeasurementBatchIn,
    actor_user_id: uuid.UUID,
    warnings: list[dict],
) -> list[Measurement]:
    rows = [
        Measurement(
            player_id=player_id,
            measured_at=batch.measured_at,
            metric=item.metric,
            value=Decimal(str(item.value)),
            unit=item.unit,
            source=MeasurementSource.COACH_LOGGED.value,
            recorded_by=actor_user_id,
            confidence=item.confidence,
        )
        for item in batch.metrics
    ]
    db.add_all(rows)
    db.flush()
    db.add(
        AuditLog(
            actor_user_id=actor_user_id,
            action="measurement.create",
            entity_type="player",
            entity_id=player_id,
            event_metadata={
                "measured_at": batch.measured_at.isoformat(),
                "measurement_ids": [str(row.id) for row in rows],
                "metrics": {item.metric: item.value for item in batch.metrics},
                # The whole point of acknowledging: a named person confirmed these.
                "acknowledged_warnings": warnings,
            },
        )
    )
    return rows


def log_measurements(
    db: Session,
    *,
    player: Player,
    batch: MeasurementBatchIn,
    actor_user_id: uuid.UUID,
    today: date | None = None,
) -> tuple[list[Measurement], list[dict]]:
    """Validate and save one visit. Raises before writing anything if it should not save."""
    today = today or date.today()
    problems = check_measurements(batch, player.date_of_birth, today)
    if problems:
        raise WriteRejected(problems)

    warnings = plausibility_warnings(db, player.id, batch)
    if warnings and not batch.acknowledge_warnings:
        raise NeedsConfirmation(warnings)

    rows = _add_measurements(
        db,
        player_id=player.id,
        batch=batch,
        actor_user_id=actor_user_id,
        warnings=warnings,
    )
    db.flush()
    return rows, warnings


def create_player(
    db: Session,
    *,
    payload: PlayerCreateIn,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    today: date | None = None,
) -> tuple[Player, list[Measurement], list[dict]]:
    """Create a player, their affiliation, and optionally their first visit, all or nothing.

    Every check runs before the first insert, so a refusal leaves nothing behind. The caller
    commits; this function only flushes.
    """
    today = today or date.today()

    problems = check_player(payload, today)
    if payload.measurements is not None:
        problems += check_measurements(payload.measurements, payload.date_of_birth, today)
    if db.get(Organization, organization_id) is None:
        problems.append("No such organization.")
    if problems:
        raise WriteRejected(problems)

    warnings: list[dict] = []
    if payload.measurements is not None:
        # A new player has no history, so only the absolute ranges can fire here.
        warnings = plausibility_warnings(db, None, payload.measurements)
        if warnings and not payload.measurements.acknowledge_warnings:
            raise NeedsConfirmation(warnings)

    minor = is_minor_on(payload.date_of_birth, today)
    # A sport that registers one gender does not ask; the check above has already refused any
    # other value.
    module = sports.registry()[payload.primary_sport]
    sex = payload.sex if payload.sex is not None else module.genders[0]
    player = Player(
        full_name=payload.full_name,
        known_as=payload.known_as,
        date_of_birth=payload.date_of_birth,
        sex=sex,
        nationality=payload.nationality,
        is_egypt_eligible=payload.is_egypt_eligible,
        primary_sport=payload.primary_sport,
        tier=payload.tier,
        position=payload.position,
        is_minor=minor,
        status=PlayerStatus.ACTIVE.value,
    )
    db.add(player)
    db.flush()

    db.add(
        PlayerOrganization(
            player_id=player.id,
            organization_id=organization_id,
            role=(
                PlayerOrganizationRole.YOUTH_PROSPECT if minor else PlayerOrganizationRole.PLAYER
            ).value,
            start_date=today,
            end_date=None,
        )
    )
    guardian = payload.consent.guardian_name if minor else None
    granted_by = f"guardian:{guardian}" if minor else "player"
    for purpose in ConsentPurpose:
        db.add(
            Consent(
                player_id=player.id,
                purpose=purpose.value,
                granted=True,
                granted_by=granted_by,
                guardian_name=guardian,
                valid_from=today,
                valid_until=None,
                document_ref=None,
            )
        )
    db.add(
        AuditLog(
            actor_user_id=actor_user_id,
            action="player.create",
            entity_type="player",
            entity_id=player.id,
            event_metadata={
                "organization_id": str(organization_id),
                "is_minor": minor,
            },
        )
    )
    db.add(
        AuditLog(
            actor_user_id=actor_user_id,
            action="consent.grant",
            entity_type="player",
            entity_id=player.id,
            event_metadata={
                "granted_by": granted_by,
                "purposes": [purpose.value for purpose in ConsentPurpose],
                "at": "signup",
            },
        )
    )

    measurements: list[Measurement] = []
    if payload.measurements is not None:
        measurements = _add_measurements(
            db,
            player_id=player.id,
            batch=payload.measurements,
            actor_user_id=actor_user_id,
            warnings=warnings,
        )
    db.flush()
    return player, measurements, warnings


# Purposes a withdrawal may end. Data storage is not one: withdrawing it means erasing the
# record, which is a separate flow.
# TODO(security): an erasure request for data_storage, and re-granting a withdrawn purpose.
WITHDRAWABLE = (ConsentPurpose.ANALYTICS.value, ConsentPurpose.SCOUTING_VISIBILITY.value)


def withdraw_consent(
    db: Session,
    *,
    player: Player,
    purposes: list[str],
    guardian_name: str | None,
    actor_user_id: uuid.UUID,
    today: date | None = None,
) -> tuple[list[str], list[str], str]:
    """End one or more consents for a player, from today. Returns (withdrawn, already, by).

    Nothing is deleted. Each granted row in effect is closed the day before, so it is no
    longer in effect today, and a row saying "not granted" from today is added, so the record
    shows when the consent ended and who ended it. An audit row records the request.
    """
    today = today or date.today()
    problems = []
    unknown = [p for p in purposes if p not in {c.value for c in ConsentPurpose}]
    if unknown:
        problems.append(f"Unknown consent purpose: {', '.join(unknown)}.")
    if ConsentPurpose.DATA_STORAGE.value in purposes:
        problems.append(
            "Data storage cannot be withdrawn here: without it the record has to be deleted, "
            "which is an erasure request, not a withdrawal."
        )
    minor = player.date_of_birth is not None and is_minor_on(player.date_of_birth, today)
    if minor and not guardian_name:
        problems.append("For a minor, name the guardian making the withdrawal.")
    if problems:
        raise WriteRejected(problems)

    withdrawn_by = f"guardian:{guardian_name}" if minor else "player"
    withdrawn: list[str] = []
    already: list[str] = []
    for purpose in dict.fromkeys(purposes):
        in_effect = list(
            db.execute(
                select(Consent)
                .where(Consent.player_id == player.id)
                .where(Consent.purpose == purpose)
                .where(Consent.granted.is_(True))
                .where(Consent.valid_from <= today)
                .where((Consent.valid_until.is_(None)) | (Consent.valid_until >= today))
            ).scalars()
        )
        if not in_effect:
            already.append(purpose)
            continue
        for row in in_effect:
            row.valid_until = today - timedelta(days=1)
        db.add(
            Consent(
                player_id=player.id,
                purpose=purpose,
                granted=False,
                granted_by=withdrawn_by,
                guardian_name=guardian_name if minor else None,
                valid_from=today,
                valid_until=None,
                document_ref=None,
            )
        )
        withdrawn.append(purpose)

    db.add(
        AuditLog(
            actor_user_id=actor_user_id,
            action="consent.withdraw",
            entity_type="player",
            entity_id=player.id,
            event_metadata={
                "withdrawn_by": withdrawn_by,
                "purposes": withdrawn,
                "already_withdrawn": already,
            },
        )
    )
    db.flush()
    return withdrawn, already, withdrawn_by
