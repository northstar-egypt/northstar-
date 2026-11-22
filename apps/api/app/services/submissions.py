"""Diaspora submissions (decision 0011): a player abroad is submitted, checked on arrival, and
verified by the federation before they become a player record.

Who does what
-------------
- **Submit**: scouts, federation staff, and players with an account (for themselves).
- **Review**: federation staff, never their own submission.
- **See a submission**: its submitter and federation staff. Nobody else learns it exists.

Consent (`consent_rule`)
------------------------
A player is not stored without the sign-up consent form (CLAUDE.md, "Consent is signed at
sign-up"). Whoever submits records it the way a coach does at `POST /players`: signed by the
player, or for a minor by a named guardian. A scout cannot record it for a minor, because a
child abroad is not someone a scout answers for: that submission waits as `awaiting_consent`
until the federation records the guardian's signature. A submission with no form recorded
waits the same way.

Checks on arrival (`run_checks`)
--------------------------------
Rerun on every change and before every decision. Only validation refuses anything; the rest is
for the reviewer, with its evidence.

1. **Validation** (`check_claims`): the same rules as a new player, plus the eligibility basis,
   country codes, a web address for the source, and each season against the sport module
   (`football.season_basic.v1`, its ranges and invariants).
2. **Same person on record**: the identity engine (`ml/identity`, decision 0010) scores the
   submission against every player and every open submission. Matches at the engine's link
   threshold are shown with their probability and what agreed and disagreed. A player who
   submits themselves is matched to their own record.
3. **Date of birth**: the engine reads a different date of birth as strong evidence of two
   people, so a re-registration with a younger date never reaches its threshold. This check
   looks for that directly: a record with the same full name and given name and a different
   date of birth is possible age misrepresentation, the fraud that matters most in youth
   football, or two people of the same name. Born within a week, it is shown as a likely match
   instead (a typing slip).
4. **Numbers**: a season whose goals or assists per 90 are above every player of its position
   group in the same league season, when at least 20 of them are on record. With fewer, it
   says there is nothing to compare with rather than guessing.
5. **The submitter**: how many submissions they made in the last 30 days, and how many were
   rejected. There is no rate limiting (docs/threat-model.md), so this is the only brake.

What approval does
------------------
`approve` creates the player through `writes.create_player` (tier `diaspora`, Egypt-eligible,
the recorded consent), affiliated to the club abroad (found by name and country, or created).
`attach` links the submission to a player already on record, changing nothing on the record.
Either way the submitted seasons stay on the submission: the profile shows them as submitted
(`submitted_seasons`), and no league analytics count them, so one submitter cannot move a
league's numbers.
"""

from __future__ import annotations

import re
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import sports
from app.models.audit_log import AuditLog
from app.models.enums import EligibilityBasis, PlayerStatus, SubmissionStatus
from app.models.organization import Organization
from app.models.performance_entry import PerformanceEntry
from app.models.player import Player
from app.models.player_organization import PlayerOrganization
from app.models.player_submission import PlayerSubmission
from app.models.user import User
from app.schemas.submissions import SubmissionConsentIn, SubmissionDecisionIn, SubmissionIn
from app.schemas.writes import PlayerCreateIn, SignupConsentIn
from app.services import forecast  # noqa: F401  (puts ml/ on the path)
from app.services import writes
from app.services.access import Caller

from ml.identity import engine  # noqa: E402

SPORT = "football"
TIER = "diaspora"
SEASON_SCHEMA = "football.season_basic.v1"
OPEN = (SubmissionStatus.PENDING, SubmissionStatus.AWAITING_CONSENT, SubmissionStatus.NEEDS_INFO)
# The numbers check: the platform's minutes for a rate (radar, gaps), and the talent
# estimates' smallest peer group.
RATE_MINUTES = 450
MIN_PEERS = 20
RECENT_DAYS = 30
# The identity model is fitted on every player, which takes seconds on a full database
# (about 6 s for 3,000 records, 18 s for 6,000), so it is fitted once and kept until the number
# of players moves by more than this share, or for an hour.
MODEL_DRIFT = 0.02
MODEL_AGE_SECONDS = 3600
_FIT: dict = {}
_SEASON = re.compile(r"^\d{4}(/\d{2})?$")
_COUNTRY = re.compile(r"^[A-Z]{2}$")


class Rejected(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


class Forbidden(Exception):
    pass


class NotFound(Exception):
    pass


def may_submit(caller: Caller) -> bool:
    return caller.is_scout or caller.is_federation or caller.is_player


def may_review(caller: Caller) -> bool:
    return caller.is_federation


# ---------------------------------------------------------------------------
# Validation and consent
# ---------------------------------------------------------------------------


def check_claims(payload: SubmissionIn, today: date) -> list[str]:
    """Every reason the submission cannot be stored. Empty means it can."""
    problems = []
    if not payload.full_name:
        problems.append("The name is empty.")
    if not payload.club_name:
        problems.append("The club is empty.")
    if payload.date_of_birth > today:
        problems.append("Date of birth is in the future.")
    else:
        age = writes._years_between(payload.date_of_birth, today)
        if not writes.MIN_AGE_YEARS <= age <= writes.MAX_AGE_YEARS:
            problems.append(f"Date of birth makes this player {age}, outside {writes.MIN_AGE_YEARS} "
                            f"to {writes.MAX_AGE_YEARS}.")
    module = sports.registry()[SPORT]
    if payload.sex is not None and payload.sex not in module.genders:
        problems.append(f"{module.label} on NorthStar registers {' and '.join(module.genders)} players only.")
    if payload.position is not None and payload.position not in module.roles:
        problems.append(f"{payload.position!r} is not a position. Expected one of: {', '.join(module.roles)}.")
    if payload.eligibility_basis not in {b.value for b in EligibilityBasis}:
        problems.append(f"Eligibility basis must be one of: {', '.join(b.value for b in EligibilityBasis)}.")
    elif payload.eligibility_basis == EligibilityBasis.OTHER and len(payload.note.strip()) < 10:
        problems.append("An eligibility basis of 'other' needs the note to say what it is.")
    if payload.eligibility_basis == EligibilityBasis.EGYPTIAN_NATIONALITY and "EG" not in payload.nationality:
        problems.append("The basis is Egyptian nationality, but EG is not among the nationalities.")
    for code in [*payload.nationality, payload.club_country]:
        if not _COUNTRY.match(code):
            problems.append(f"{code!r} is not a two-letter country code (ISO 3166-1, e.g. EG, DE).")
    url = urlparse(payload.source_url.strip())
    if url.scheme not in ("http", "https") or "." not in url.netloc:
        problems.append("The source must be a web address (https://...) where the claims can be checked.")
    seen = set()
    for i, season in enumerate(payload.seasons, start=1):
        if not _SEASON.match(season.season):
            problems.append(f"Season {i}: {season.season!r} is not a season like 2024/25 or 2025.")
        if (season.competition, season.season) in seen:
            problems.append(f"Season {i}: {season.competition} {season.season} is given twice.")
        seen.add((season.competition, season.season))
        problems += [f"Season {i}: {p}" for p in sports.validate(season.metrics, SEASON_SCHEMA)]
    return problems


def consent_rule(caller: Caller, payload: SubmissionIn, today: date) -> tuple[dict, str]:
    """(the consent as recorded, the status the submission starts in)."""
    minor = writes.is_minor_on(payload.date_of_birth, today)
    form = payload.consent
    recorded = form is not None and form.signed and (not minor or bool(form.guardian_name))
    if caller.is_scout and minor:
        recorded = False
    if not recorded:
        return {"signed": False, "guardianName": None}, SubmissionStatus.AWAITING_CONSENT.value
    return ({"signed": True, "guardianName": form.guardian_name if minor else None,
             "recordedBy": str(caller.user_id), "on": today.isoformat()},
            SubmissionStatus.PENDING.value)


# ---------------------------------------------------------------------------
# Checks on arrival
# ---------------------------------------------------------------------------


def _record(s: PlayerSubmission) -> engine.Record:
    return engine.Record(
        id=f"submission:{s.id}", names=[n for n in (s.full_name, s.known_as) if n], sex=s.sex, sport=s.sport,
        date_of_birth=s.date_of_birth, nationality=frozenset(s.nationality or []),
        clubs=frozenset([s.club_name]), source="submission",
    )


def _player_records(db: Session) -> dict[str, engine.Record]:
    clubs: dict[str, set[str]] = defaultdict(set)
    for pid, name in db.execute(select(PlayerOrganization.player_id, Organization.name)
                                .join(Organization, Organization.id == PlayerOrganization.organization_id)):
        clubs[str(pid)].add(name)
    out = {}
    for p in db.execute(select(Player).where(Player.status != PlayerStatus.MERGED.value)).scalars():
        out[str(p.id)] = engine.Record(
            id=str(p.id), names=[n for n in (p.full_name, p.known_as) if n], sex=p.sex, sport=p.primary_sport,
            date_of_birth=p.date_of_birth, nationality=frozenset(p.nationality or []),
            clubs=frozenset(clubs.get(str(p.id), set())), source="player")
    return out


def _fitted(players: list[engine.Record]):
    """The identity model fitted on the players on record (`engine.score`), with the name-word
    shares its term-frequency adjustment reads. Kept between submissions (MODEL_DRIFT)."""
    now, n = time.monotonic(), len(players)
    if _FIT and abs(n - _FIT["n"]) <= MODEL_DRIFT * _FIT["n"] and now - _FIT["at"] < MODEL_AGE_SECONDS:
        return _FIT["model"], _FIT["shares"], _FIT["u_avg"]
    _, model = engine.score(players)
    # The share of true pairs: the register's own estimate answers "how many of these records are
    # duplicates of each other", which is not the question here, and on a register with no
    # duplicates it falls to nothing, so that no submission could ever match. Below the engine's
    # own starting value (a tenth of the records duplicated), the starting value is used.
    everything = max(1, n * (n - 1) // 2)
    model = replace(model, prior=max(model.prior, min(0.5, 0.1 * n / everything)))
    shares = engine.term_shares(players)
    _FIT.update(n=n, at=now, model=model, shares=shares, u_avg=sum(x * x for x in shares.values()))
    return model, shares, _FIT["u_avg"]


def _score_one(mine: engine.Record, records: dict[str, engine.Record]) -> list[engine.ScoredPair]:
    """The submission against every record, with the engine's own blocking (`engine.candidates`:
    enough shared name keys, none of them in more than MAX_POSTING records, and nothing ruling
    the pair out) and its own scoring, but only the pairs that include the submission."""
    model, shares, u_avg = _fitted([r for k, r in records.items() if not k.startswith("submission:")])
    their_keys = {k: engine.keys(r) for k, r in records.items()}
    posting = Counter(key for ks in their_keys.values() for key in ks)
    mine_keys = {k for k in engine.keys(mine) if posting[k] + 1 <= engine.MAX_POSTING}
    out = []
    for k, r in records.items():
        need = max(1, min(2, len(mine_keys), len(their_keys[k])))
        if len(mine_keys & their_keys[k]) < need or not engine._compatible(mine, r):
            continue
        vector = engine.compare(mine, r)
        offset = engine.tf_offset(mine, r, vector["name"], shares, u_avg)
        out.append(engine.ScoredPair(mine.id, r.id, model.probability(vector, offset), vector))
    return out


def _identity(db: Session, s: PlayerSubmission, caller_player: uuid.UUID | None) -> tuple[dict, dict]:
    records = _player_records(db)
    others = db.execute(select(PlayerSubmission).where(
        PlayerSubmission.id != s.id, PlayerSubmission.status.in_([x.value for x in OPEN]))).scalars().all()
    for other in others:
        records[f"submission:{other.id}"] = _record(other)
    mine = _record(s)
    scored = _score_one(mine, records)
    found, twins = [], []
    for pair in scored:
        if mine.id not in (pair.a, pair.b):
            continue
        other = records[pair.b if pair.a == mine.id else pair.a]
        same_name = pair.levels.get("name") == "all" and pair.levels.get("given") == "same"
        if pair.probability >= engine.LINK or (same_name and pair.levels.get("dob") == "near"):
            found.append((pair, other))
        elif same_name and pair.levels.get("dob") == "conflict":
            twins.append((pair, other))
    found.sort(key=lambda x: -x[0].probability)
    names = {str(o.id): o.full_name for o in others}

    def described(pair, other) -> dict:
        is_submission = other.id.startswith("submission:")
        return {
            "kind": "submission" if is_submission else "player",
            "id": other.id.split(":", 1)[1] if is_submission else other.id,
            "fullName": names.get(other.id.split(":", 1)[1]) if is_submission else other.names[0],
            "dateOfBirth": other.date_of_birth.isoformat() if other.date_of_birth else None,
            "probability": round(pair.probability, 3),
            "evidence": engine.evidence(pair, mine, other),
            "dobLevel": pair.levels.get("dob"),
        }

    matches = [described(pair, other) for pair, other in found[:5]]
    if caller_player is not None and str(caller_player) in records and not any(
            m["kind"] == "player" and m["id"] == str(caller_player) for m in matches):
        own = records[str(caller_player)]
        matches.insert(0, {"kind": "player", "id": own.id, "fullName": own.names[0],
                           "dateOfBirth": own.date_of_birth.isoformat() if own.date_of_birth else None,
                           "probability": None, "evidence": ["Submitted by this player's own account"],
                           "dobLevel": engine.dob_level(mine, own)})
    if matches:
        identity = {"key": "identity", "label": "Same person on record", "outcome": "attention",
                    "summary": f"{len(matches)} likely match{'es' if len(matches) > 1 else ''} on record. "
                               "Decide whether this is a new person or one of them.", "matches": matches}
    else:
        identity = {"key": "identity", "label": "Same person on record", "outcome": "clear",
                    "summary": f"No record reaches the identity engine's link threshold ({engine.LINK}).",
                    "matches": []}
    conflicts = [m for m in matches if m["dobLevel"] == "conflict"] + [described(p, o) for p, o in twins[:5]]
    if conflicts:
        dob = {"key": "date_of_birth", "label": "Date of birth", "outcome": "attention",
               "summary": "Someone on record has the same name and a different date of birth ("
                          + ", ".join(f"{m['fullName']}: {m['dateOfBirth']}" for m in conflicts)
                          + f", against {s.date_of_birth.isoformat()} here). Possible age misrepresentation, "
                            "or two different people.", "matches": conflicts}
    else:
        dob = {"key": "date_of_birth", "label": "Date of birth", "outcome": "clear",
               "summary": "Nobody on record has the same name and a different date of birth.", "matches": []}
    return identity, dob


def _numbers(db: Session, s: PlayerSubmission) -> dict:
    unusual, compared, alone = [], 0, []
    for season in s.seasons or []:
        metrics = season["metrics"]
        minutes = metrics.get("minutes_played", 0)
        group = metrics.get("position_group")
        label = f"{season['competition']} {season['season']}"
        if minutes < RATE_MINUTES or not group:
            alone.append(f"{label} (under {RATE_MINUTES} minutes or no position group)")
            continue
        peers = [e.metrics for e in db.execute(select(PerformanceEntry).where(
            PerformanceEntry.schema_ref == SEASON_SCHEMA, PerformanceEntry.event == label)).scalars()
            if e.metrics.get("position_group") == group and e.metrics.get("minutes_played", 0) >= RATE_MINUTES]
        if len(peers) < MIN_PEERS:
            alone.append(f"{label} ({len(peers)} {group}s on record; {MIN_PEERS} are needed)")
            continue
        compared += 1
        for key, words in (("goals", "goals"), ("assists", "assists")):
            mine = metrics.get(key, 0) * 90 / minutes
            best = max(p.get(key, 0) * 90 / p["minutes_played"] for p in peers)
            if mine > best:
                unusual.append(f"{label}: {mine:.2f} {words} per 90, above every one of {len(peers)} {group}s "
                               f"on record (the highest {best:.2f})")
    if unusual:
        return {"key": "numbers", "label": "Numbers", "outcome": "attention",
                "summary": "; ".join(unusual) + ". Check them against the source."}
    if compared:
        return {"key": "numbers", "label": "Numbers", "outcome": "clear",
                "summary": f"Within the range of the league's players in {compared} season(s)."
                           + (f" Nothing to compare with for {'; '.join(alone)}." if alone else "")}
    if s.seasons:
        return {"key": "numbers", "label": "Numbers", "outcome": "not_run",
                "summary": f"Nothing to compare with: {'; '.join(alone)}."}
    return {"key": "numbers", "label": "Numbers", "outcome": "not_run", "summary": "No seasons were submitted."}


def _submitter(db: Session, s: PlayerSubmission, now: datetime) -> dict:
    if s.submitted_by_user_id is None:
        return {"key": "submitter", "label": "Submitter", "outcome": "info", "summary": "The account no longer exists."}
    mine = PlayerSubmission.submitted_by_user_id == s.submitted_by_user_id
    recent = db.execute(select(func.count()).select_from(PlayerSubmission).where(
        mine, PlayerSubmission.created_at >= now - timedelta(days=RECENT_DAYS))).scalar_one()
    rejected = db.execute(select(func.count()).select_from(PlayerSubmission).where(
        mine, PlayerSubmission.status == SubmissionStatus.REJECTED.value)).scalar_one()
    outcome = "attention" if rejected else "info"
    return {"key": "submitter", "label": "Submitter", "outcome": outcome,
            "summary": f"{recent} submission(s) from this account in the last {RECENT_DAYS} days; "
                       f"{rejected} of theirs rejected so far."}


def run_checks(db: Session, s: PlayerSubmission, caller_player: uuid.UUID | None = None) -> list[dict]:
    db.flush()
    identity, dob = _identity(db, s, caller_player)
    return [
        {"key": "validation", "label": "Validation", "outcome": "clear",
         "summary": "The claims and seasons pass the platform's rules."},
        identity, dob, _numbers(db, s), _submitter(db, s, datetime.now(timezone.utc)),
    ]


# ---------------------------------------------------------------------------
# Submit, edit, consent
# ---------------------------------------------------------------------------


def _apply(s: PlayerSubmission, payload: SubmissionIn) -> None:
    s.full_name, s.known_as, s.date_of_birth, s.sex = payload.full_name, payload.known_as, payload.date_of_birth, payload.sex
    s.nationality, s.eligibility_basis, s.position = payload.nationality, payload.eligibility_basis, payload.position
    s.club_name, s.club_country, s.competition = payload.club_name, payload.club_country, payload.competition
    s.source_url, s.note = payload.source_url.strip(), payload.note.strip()
    s.seasons = [{"competition": x.competition, "season": x.season, "metrics": x.metrics} for x in payload.seasons]


def _audit(db: Session, caller: Caller, action: str, s: PlayerSubmission, **meta) -> None:
    db.add(AuditLog(actor_user_id=caller.user_id, action=action, entity_type="player_submission",
                    entity_id=s.id, event_metadata={"status": s.status, **meta}))


def submit(db: Session, caller: Caller, payload: SubmissionIn, today: date | None = None) -> PlayerSubmission:
    if not may_submit(caller):
        raise Forbidden
    today = today or date.today()
    problems = check_claims(payload, today)
    if problems:
        raise Rejected(problems)
    consent, status = consent_rule(caller, payload, today)
    s = PlayerSubmission(id=uuid.uuid4(), submitted_by_user_id=caller.user_id, submitter_role=caller.role,
                         status=status, sport=SPORT, consent=consent)
    _apply(s, payload)
    db.add(s)
    s.checks = run_checks(db, s, caller.linked_player_id if caller.is_player else None)
    _audit(db, caller, "submission.create", s)
    db.flush()
    return s


def get(db: Session, caller: Caller, submission_id: uuid.UUID) -> PlayerSubmission:
    s = db.get(PlayerSubmission, submission_id)
    # Not found, rather than forbidden, for anyone else: they do not learn it exists.
    if s is None or not (may_review(caller) or s.submitted_by_user_id == caller.user_id):
        raise NotFound
    return s


def update(db: Session, caller: Caller, submission_id: uuid.UUID, payload: SubmissionIn,
           today: date | None = None) -> PlayerSubmission:
    s = get(db, caller, submission_id)
    if s.submitted_by_user_id != caller.user_id:
        raise Forbidden
    if s.status not in {x.value for x in OPEN}:
        raise Rejected([f"A submission that is {s.status.replace('_', ' ')} cannot be changed."])
    today = today or date.today()
    problems = check_claims(payload, today)
    if problems:
        raise Rejected(problems)
    consent, status = consent_rule(caller, payload, today)
    if status == SubmissionStatus.AWAITING_CONSENT and s.consent.get("signed") and \
            writes.is_minor_on(payload.date_of_birth, today) == writes.is_minor_on(s.date_of_birth, today):
        # Consent the federation already recorded stays recorded.
        consent, status = s.consent, SubmissionStatus.PENDING.value
    _apply(s, payload)
    s.consent, s.status = consent, status
    s.checks = run_checks(db, s, caller.linked_player_id if caller.is_player else None)
    _audit(db, caller, "submission.update", s)
    db.flush()
    return s


def record_consent(db: Session, caller: Caller, submission_id: uuid.UUID, form: SubmissionConsentIn,
                   today: date | None = None) -> PlayerSubmission:
    if not may_review(caller):
        raise Forbidden
    s = get(db, caller, submission_id)
    if s.status != SubmissionStatus.AWAITING_CONSENT:
        raise Rejected(["This submission is not waiting for consent."])
    today = today or date.today()
    minor = writes.is_minor_on(s.date_of_birth, today)
    if not form.signed:
        raise Rejected(["The consent form has not been signed."])
    if minor and not form.guardian_name:
        raise Rejected(["This player is a minor, so the consent form must be signed by a named guardian."])
    s.consent = {"signed": True, "guardianName": form.guardian_name if minor else None,
                 "recordedBy": str(caller.user_id), "on": today.isoformat()}
    s.status = SubmissionStatus.PENDING.value
    _audit(db, caller, "submission.consent", s, guardian=bool(minor))
    db.flush()
    return s


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------


def _club(db: Session, caller: Caller, s: PlayerSubmission) -> Organization:
    """The club abroad: the one on record with this name and country, or a new one."""
    org = db.execute(select(Organization).where(
        func.lower(Organization.name) == s.club_name.lower(), Organization.country == s.club_country,
        Organization.type == "club")).scalars().first()
    if org is None:
        org = Organization(name=s.club_name, type="club", sport=SPORT, country=s.club_country)
        db.add(org)
        db.flush()
        db.add(AuditLog(actor_user_id=caller.user_id, action="organization.create", entity_type="organization",
                        entity_id=org.id, event_metadata={"from_submission": str(s.id)}))
    return org


def decide(db: Session, caller: Caller, submission_id: uuid.UUID, decision: SubmissionDecisionIn,
           today: date | None = None) -> PlayerSubmission:
    if not may_review(caller):
        raise Forbidden
    s = get(db, caller, submission_id)
    if s.submitted_by_user_id == caller.user_id:
        raise Forbidden
    today = today or date.today()
    action = decision.action
    if action not in ("approve", "attach", "reject", "needs_info"):
        raise Rejected(["The decision must be approve, attach, reject or needs_info."])
    allowed = {"approve": {SubmissionStatus.PENDING}, "attach": {SubmissionStatus.PENDING},
               "reject": set(OPEN), "needs_info": {SubmissionStatus.PENDING, SubmissionStatus.AWAITING_CONSENT}}
    if s.status not in {x.value for x in allowed[action]}:
        raise Rejected([f"A submission that is {s.status.replace('_', ' ')} cannot be given '{action}'."])

    if action == "approve":
        payload = PlayerCreateIn(
            full_name=s.full_name, known_as=s.known_as, date_of_birth=s.date_of_birth, sex=s.sex,
            nationality=s.nationality, is_egypt_eligible=True, primary_sport=SPORT, tier=TIER, position=s.position,
            consent=SignupConsentIn(signed=True, guardian_name=s.consent.get("guardianName")))
        try:
            player, _, _ = writes.create_player(db, payload=payload, organization_id=_club(db, caller, s).id,
                                                actor_user_id=caller.user_id, today=today)
        except writes.WriteRejected as exc:
            raise Rejected(exc.problems) from None
        s.player_id = player.id
        s.status = SubmissionStatus.APPROVED.value
    elif action == "attach":
        player = db.get(Player, decision.player_id) if decision.player_id else None
        if player is None or player.status == PlayerStatus.MERGED:
            raise Rejected(["Attach needs the player on record this submission is, and they must not be merged."])
        s.player_id = player.id
        s.status = SubmissionStatus.APPROVED.value
    elif action == "reject":
        s.status = SubmissionStatus.REJECTED.value
    else:
        s.status = SubmissionStatus.NEEDS_INFO.value
    s.reviewed_by_user_id, s.reviewed_at, s.review_reason = caller.user_id, datetime.now(timezone.utc), decision.reason
    _audit(db, caller, f"submission.{action}", s, reason=decision.reason,
           player_id=str(s.player_id) if s.player_id else None)
    db.flush()
    return s


def queue(db: Session, caller: Caller, status: str | None) -> list[PlayerSubmission]:
    """For federation staff: oldest first, so nothing waits for ever behind newer ones."""
    if not may_review(caller):
        raise Forbidden
    query = select(PlayerSubmission).order_by(PlayerSubmission.created_at)
    if status:
        query = query.where(PlayerSubmission.status == status)
    else:
        query = query.where(PlayerSubmission.status.in_([x.value for x in OPEN]))
    return list(db.execute(query.limit(200)).scalars())


def mine(db: Session, caller: Caller) -> list[PlayerSubmission]:
    return list(db.execute(select(PlayerSubmission).where(PlayerSubmission.submitted_by_user_id == caller.user_id)
                           .order_by(PlayerSubmission.created_at.desc()).limit(200)).scalars())


def out(db: Session, caller: Caller, s: PlayerSubmission, today: date | None = None) -> dict:
    today = today or date.today()
    name = db.get(User, s.submitted_by_user_id).full_name if s.submitted_by_user_id else None
    data = {c.key: getattr(s, c.key) for c in PlayerSubmission.__table__.columns}
    data.update(is_minor=writes.is_minor_on(s.date_of_birth, today), submitted_by_name=name,
                mine=s.submitted_by_user_id == caller.user_id)
    return data


# ---------------------------------------------------------------------------
# On the profile
# ---------------------------------------------------------------------------


def submitted_seasons(db: Session, player: Player) -> dict:
    rows = db.execute(select(PlayerSubmission).where(
        PlayerSubmission.player_id == player.id, PlayerSubmission.status == SubmissionStatus.APPROVED.value)
        .order_by(PlayerSubmission.reviewed_at.desc())).scalars().all()
    if not rows:
        return {"submissions": [], "note": None}
    return {
        "submissions": [{
            "submissionId": str(s.id), "clubName": s.club_name, "clubCountry": s.club_country,
            "competition": s.competition, "sourceUrl": s.source_url, "submitterRole": s.submitter_role,
            "approvedAt": s.reviewed_at.isoformat() if s.reviewed_at else None, "seasons": s.seasons,
        } for s in rows],
        "note": "Submitted and checked by the federation, not from a data source. These seasons are not "
                "counted in any league comparison.",
    }
