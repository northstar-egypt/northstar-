"""Parts 6 to 9 of "find the next <pro>": weekly report, game journey, academy leaderboard and
scout alert. They need two new tables, `drill_log` (migration 0010) and `match_watch` (0011),
kept in their own migrations so they can be dropped if the feature is not kept.

Nothing here is a model or a prediction. Everything is counted from the record:

- **XP** (`xp`): 1 point per 10 minutes played in academy matches, and `XP_PER_DRILL` per drill
  logged. Fixed, simple rules a child can understand; there is no hidden scoring.
- **Levels** (`LEVELS`): XP thresholds. The names are placeholders the team has not settled.
- **Badges** (`BADGES`): milestones on minutes and drills, and a "style twin" badge when the
  player's best match to any professional (ml/next_pro.py) is at least `TWIN_PERCENT`.
- **Idol** and "% closer": the professional the player matches best now, and the match to that
  same professional using only matches before `IDOL_WEEKS` weeks ago. Shown only when both can
  be computed.
- **Weekly report**: matches, minutes, drills and XP in the last 7 days; statistics that rose
  or fell by at least `CHANGE` between the last 4 weeks and the 4 before (each window needs
  `WINDOW_MIN_MINUTES`, or the report says there is not enough); and a next goal from the
  player's weakest point (app/services/weak_points.py). Academy matches are often weekly or
  less, so one week is too little to judge a statistic by; four is the shortest honest window.
- **Leaderboard**: XP earned in the last 7 days among the youth players the caller may see,
  with analytics consent in effect (ranking children is analytics on their data).
- **Scout alert**: a scout follows an academy player against one professional; when the style
  match has risen by `ALERT_JUMP` points since they last looked, it is an alert.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.drill_log import DrillLog
from app.models.enums import ConsentPurpose, FootballTier
from app.models.match_watch import MatchWatch
from app.models.performance_entry import PerformanceEntry
from app.models.player import Player
from app.services import cohort, next_pro, weak_points
from app.services.access import Caller, consent_subquery, has_consent, may_view, visible_players

from ml import next_pro as N  # noqa: E402

XP_PER_DRILL = 20
LEVELS = [(0, "Academy Rookie"), (200, "Rising Talent"), (600, "Academy Star"), (1200, "Future Pro")]
TWIN_PERCENT = 75
IDOL_WEEKS = 8
CHANGE = 0.15
WINDOW_MIN_MINUTES = 180
ALERT_JUMP = 10
SCHEMA = next_pro.YOUTH_SCHEMA
RATES = ("goals", "assists", "shots", "key_passes", "passes_attempted", "tackles", "distance_km")
LABELS = {"goals": "goals", "assists": "assists", "shots": "shots", "key_passes": "key passes",
          "passes_attempted": "passes", "tackles": "tackles", "distance_km": "distance (km)",
          "pass_completion": "pass completion"}
BADGES = [
    ("first_drill", "First drill", lambda s: s["drills"] >= 1),
    ("ten_drills", "Ten drills", lambda s: s["drills"] >= 10),
    ("regular", "900 minutes played", lambda s: s["minutes"] >= 900),
    ("iron", "2,700 minutes played", lambda s: s["minutes"] >= 2700),
    ("style_twin", f"Style twin: {TWIN_PERCENT}%+ match with a pro", lambda s: (s["idol"] or 0) >= TWIN_PERCENT),
]


def _minutes(db: Session, player_ids: list, since: date | None = None, until: date | None = None) -> dict[str, float]:
    query = (select(PerformanceEntry.player_id,
                    func.sum(PerformanceEntry.metrics["minutes_played"].as_float()))
             .where(PerformanceEntry.schema_ref == SCHEMA, PerformanceEntry.player_id.in_(player_ids))
             .group_by(PerformanceEntry.player_id))
    if since:
        query = query.where(PerformanceEntry.period_start >= since)
    if until:
        query = query.where(PerformanceEntry.period_start < until)
    return {str(p): float(m or 0) for p, m in db.execute(query).all()}


def _drills(db: Session, player_ids: list, since: date | None = None) -> dict[str, int]:
    query = (select(DrillLog.player_id, func.count()).where(DrillLog.player_id.in_(player_ids))
             .group_by(DrillLog.player_id))
    if since:
        query = query.where(DrillLog.done_on >= since)
    return {str(p): int(n) for p, n in db.execute(query).all()}


def xp(minutes: float, drills: int) -> int:
    return int(minutes // 10) + XP_PER_DRILL * drills


def level(points: int) -> dict:
    current = max((lv for lv in LEVELS if points >= lv[0]), key=lambda lv: lv[0])
    following = next((lv for lv in LEVELS if lv[0] > points), None)
    return {"name": current[1], "next_name": following[1] if following else None,
            "next_at": following[0] if following else None}


# ---------------------------------------------------------------------------
# Game journey (part 7)
# ---------------------------------------------------------------------------

def journey(db: Session, caller: Caller, player: Player, today: date | None = None) -> dict:
    today = today or date.today()
    if not has_consent(db, player.id, ConsentPurpose.ANALYTICS.value):
        return {"xp": None, "level": None, "badges": [], "idol": None,
                "note": "Analytics consent is not in effect for this player, so there is no journey."}
    minutes = _minutes(db, [player.id]).get(str(player.id), 0.0)
    drills = _drills(db, [player.id]).get(str(player.id), 0)
    points = xp(minutes, drills)

    idol_block = None
    pros = next_pro._pros(db)
    now = N.idol(str(player.id), pros, next_pro._youth(db))
    if now is not None:
        pro = db.get(Player, now[0])
        if pro is not None and may_view(db, caller, pro)[0]:
            before = N.percent_between(now[0], str(player.id), pros,
                                       next_pro._youth(db, before=today - timedelta(weeks=IDOL_WEEKS)))
            idol_block = {"pro_id": pro.id, "name": pro.known_as or pro.full_name,
                          "position": pro.position, "percent": now[1], "before": before,
                          "weeks": IDOL_WEEKS}
    stats = {"minutes": minutes, "drills": drills, "idol": idol_block["percent"] if idol_block else None}
    return {
        "xp": points,
        "level": level(points),
        "minutes": int(minutes),
        "drills": drills,
        "badges": [{"key": k, "label": label, "earned": bool(rule(stats))} for k, label, rule in BADGES],
        "idol": idol_block,
        "note": (f"XP: 1 per 10 minutes played and {XP_PER_DRILL} per drill done. Level names are "
                 "placeholders. The idol is the professional whose style this player matches best "
                 f"now, compared with the same match from matches up to {IDOL_WEEKS} weeks ago."),
    }


# ---------------------------------------------------------------------------
# Weekly report (part 6)
# ---------------------------------------------------------------------------

def _window(db: Session, player: Player, since: date, until: date) -> dict[str, float] | None:
    totals: dict[str, float] = {}
    for (metrics,) in db.execute(
        select(PerformanceEntry.metrics).where(
            PerformanceEntry.player_id == player.id, PerformanceEntry.schema_ref == SCHEMA,
            PerformanceEntry.period_start >= since, PerformanceEntry.period_start < until)
    ).all():
        for k, v in (metrics or {}).items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                totals[k] = totals.get(k, 0) + v
    minutes = totals.get("minutes_played", 0)
    if minutes < WINDOW_MIN_MINUTES:
        return None
    out = {k: totals[k] / minutes * 90 for k in RATES if k in totals}
    if totals.get("passes_attempted"):
        out["pass_completion"] = totals.get("passes_completed", 0) / totals["passes_attempted"] * 100
    return out


def weekly_report(db: Session, player: Player, today: date | None = None) -> dict:
    today = today or date.today()
    if not has_consent(db, player.id, ConsentPurpose.ANALYTICS.value):
        return {"week": None, "improved": [], "dropped": [], "goal": None,
                "note": "Analytics consent is not in effect for this player, so there is no report."}
    tomorrow = today + timedelta(days=1)
    week_start = today - timedelta(days=6)
    matches = db.execute(select(func.count()).where(
        PerformanceEntry.player_id == player.id, PerformanceEntry.schema_ref == SCHEMA,
        PerformanceEntry.period_start >= week_start, PerformanceEntry.period_start < tomorrow)).scalar_one()
    minutes = _minutes(db, [player.id], since=week_start, until=tomorrow).get(str(player.id), 0.0)
    drills = _drills(db, [player.id], since=week_start).get(str(player.id), 0)

    recent = _window(db, player, today - timedelta(weeks=4), tomorrow)
    earlier = _window(db, player, today - timedelta(weeks=8), today - timedelta(weeks=4))
    improved, dropped = [], []
    if recent and earlier:
        for k, now in recent.items():
            was = earlier.get(k)
            if not was:
                continue
            change = (now - was) / was
            row = {"key": k, "label": LABELS.get(k, k), "before": round(was, 2), "now": round(now, 2),
                   "unit": "%" if k == "pass_completion" else "per 90"}
            if change >= CHANGE:
                improved.append(row)
            elif change <= -CHANGE:
                dropped.append(row)

    goal = None
    wp = weak_points.weak_points(db, player)
    if wp["items"]:
        w = wp["items"][0]
        drill = w["drills"][0]["name"] if w["drills"] else None
        target = recent.get(w["key"]) if recent else None
        goal = (f"Work on {w['label'].lower()}"
                + (f": do the \"{drill}\" drill twice this week" if drill else "")
                + (f", and beat your last 4 weeks' {round(target, 2)} {w['unit']}" if target is not None else "")
                + ".")
    if recent is None or earlier is None:
        trend_note = (f"Not enough matches to say what went up or down: each 4-week window needs "
                      f"{WINDOW_MIN_MINUTES} minutes.")
    else:
        trend_note = (f"Up or down means a change of at least {int(CHANGE * 100)}% per 90 between the "
                      "last 4 weeks and the 4 weeks before. Academy matches are weekly at most, so one "
                      "week alone is too little to judge a statistic.")
    return {
        "week": {"from": week_start.isoformat(), "to": today.isoformat(), "matches": int(matches),
                 "minutes": int(minutes), "drills": drills, "xp": xp(minutes, drills)},
        "improved": improved,
        "dropped": dropped,
        "goal": goal,
        "note": trend_note,
    }


# ---------------------------------------------------------------------------
# Drills done (feeds parts 6 to 8)
# ---------------------------------------------------------------------------

def log_drill(db: Session, caller: Caller, player: Player, statistic: str, drill: str,
              today: date | None = None) -> DrillLog:
    row = DrillLog(player_id=player.id, logged_by=caller.user_id, done_on=today or date.today(),
                   statistic=statistic[:40], drill=drill[:120])
    db.add(row)
    db.flush()
    db.add(AuditLog(actor_user_id=caller.user_id, action="drill.create", entity_type="player",
                    entity_id=player.id, event_metadata={"drill_log_id": str(row.id),
                                                         "statistic": row.statistic, "drill": row.drill}))
    return row


# ---------------------------------------------------------------------------
# Academy leaderboard (part 8)
# ---------------------------------------------------------------------------

def leaderboard(db: Session, caller: Caller, today: date | None = None, shown: int = 10) -> dict:
    today = today or date.today()
    since = today - timedelta(days=6)
    consented = select(consent_subquery(ConsentPurpose.ANALYTICS.value).subquery().c.player_id)
    players = {str(p.id): p for p in db.execute(
        visible_players(caller).where(Player.tier == FootballTier.YOUTH.value,
                                      Player.primary_sport == "football",
                                      Player.id.in_(consented))).scalars()}
    if not players:
        return {"items": [], "note": "No academy players to rank."}
    ids = list(players)
    minutes = _minutes(db, ids, since=since, until=today + timedelta(days=1))
    drills = _drills(db, ids, since=since)
    ranked = sorted(((pid, xp(minutes.get(pid, 0), drills.get(pid, 0))) for pid in ids),
                    key=lambda item: (-item[1], players[item[0]].full_name))
    items = []
    for pid, points in ranked:
        if points <= 0:
            break
        p = players[pid]
        if not may_view(db, caller, p)[0]:
            continue
        items.append({"player_id": p.id, "full_name": p.full_name, "position": p.position,
                      "age_label": cohort.age_label(p.date_of_birth, today), "xp": points,
                      "minutes": int(minutes.get(pid, 0)), "drills": drills.get(pid, 0)})
        if len(items) == shown:
            break
    return {"items": items, "note": (
        f"XP earned from {since.isoformat()} to {today.isoformat()}: 1 per 10 minutes played and "
        f"{XP_PER_DRILL} per drill done. Only academy players you may see, with analytics consent.")}


# ---------------------------------------------------------------------------
# Scout alert (part 9)
# ---------------------------------------------------------------------------

def watch(db: Session, caller: Caller, player: Player, pro: Player) -> dict:
    percent = N.percent_between(str(pro.id), str(player.id), next_pro._pros(db), next_pro._youth(db))
    row = db.execute(select(MatchWatch).where(MatchWatch.user_id == caller.user_id,
                                              MatchWatch.player_id == player.id,
                                              MatchWatch.pro_id == pro.id)).scalar_one_or_none()
    if row is None:
        row = MatchWatch(user_id=caller.user_id, player_id=player.id, pro_id=pro.id)
        db.add(row)
    row.last_percent = percent
    db.flush()
    return {"player_id": player.id, "pro_id": pro.id, "percent": percent}


def unwatch(db: Session, caller: Caller, player_id, pro_id) -> None:
    row = db.execute(select(MatchWatch).where(MatchWatch.user_id == caller.user_id,
                                              MatchWatch.player_id == player_id,
                                              MatchWatch.pro_id == pro_id)).scalar_one_or_none()
    if row is not None:
        db.delete(row)
        db.flush()


def alerts(db: Session, caller: Caller, mark_seen: bool = False) -> dict:
    rows = db.execute(select(MatchWatch).where(MatchWatch.user_id == caller.user_id)
                      .order_by(MatchWatch.created_at)).scalars().all()
    if not rows:
        return {"items": [], "note": "You are not following anyone yet. Use \"Watch\" on a "
                                     "\"Find the next\" list."}
    pros, youth = next_pro._pros(db), next_pro._youth(db)
    items = []
    for row in rows:
        player, pro = db.get(Player, row.player_id), db.get(Player, row.pro_id)
        if player is None or pro is None or not may_view(db, caller, player)[0] or not may_view(db, caller, pro)[0]:
            continue
        now = N.percent_between(str(pro.id), str(player.id), pros, youth)
        jump = now - row.last_percent if now is not None and row.last_percent is not None else None
        items.append({"player_id": player.id, "full_name": player.full_name,
                      "pro_id": pro.id, "pro_name": pro.known_as or pro.full_name,
                      "before": row.last_percent, "now": now,
                      "alert": jump is not None and jump >= ALERT_JUMP})
        if mark_seen and now is not None:
            row.last_percent = now
    db.flush()
    return {"items": items, "note": (
        f"An alert means the style match has risen by {ALERT_JUMP} points or more since you last "
        "marked these as seen. A higher match says the styles are closer, not that the player "
        "is better.")}
