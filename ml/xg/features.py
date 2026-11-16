"""What a shot looked like at the moment it was taken, from a StatsBomb shot event.

Only what was knowable before the ball was struck: where the shooter stood, the angle the
goal offered, how the shot was taken, how the chance was created, and where the defenders and
the goalkeeper were (StatsBomb's freeze frame, recorded for every shot). Never where the ball
went (`end_location`, the outcome), which would leak the answer.

Pitch: StatsBomb's 120 by 80, the shooting team attacking the goal at x = 120, posts at
y = 36 and y = 44.
"""

from __future__ import annotations

import math

GOAL_X, POST_LOW, POST_HIGH = 120.0, 36.0, 44.0
GOAL_CENTRE = (GOAL_X, 40.0)

BODY_PARTS = ("foot", "head", "other")
SHOT_TYPES = ("open_play", "free_kick", "corner")
TECHNIQUES = ("normal", "volley", "half_volley", "lob", "backheel", "overhead", "diving_header")
PATTERNS = ("regular", "counter", "corner", "free_kick", "throw_in", "goal_kick", "keeper", "kick_off", "other")
ASSISTS = ("none", "ground", "low", "high", "through_ball", "cross", "cut_back")

NUMERIC = (
    "distance", "angle", "under_pressure", "first_time", "one_on_one", "open_goal", "follows_dribble",
    "defenders_in_cone", "players_in_cone", "keeper_to_shooter", "keeper_off_line", "keeper_off_centre",
    "nearest_defender",
)
CATEGORICAL = {"body_part": BODY_PARTS, "shot_type": SHOT_TYPES, "technique": TECHNIQUES,
               "pattern": PATTERNS, "assist": ASSISTS}


def _snake(name: str | None) -> str:
    return (name or "").strip().lower().replace(" ", "_").replace("-", "_")


def goal_angle(x: float, y: float) -> float:
    """The angle, in radians, between the lines from the ball to the two posts."""
    a = math.atan2(POST_HIGH - y, GOAL_X - x)
    b = math.atan2(POST_LOW - y, GOAL_X - x)
    return abs(a - b)


def _in_triangle(p, a, b, c) -> bool:
    def sign(p1, p2, p3):
        return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])
    d1, d2, d3 = sign(p, a, b), sign(p, b, c), sign(p, c, a)
    return not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0))


def _assist(shot: dict, events_by_id: dict) -> str:
    key = events_by_id.get(shot.get("key_pass_id")) if shot.get("key_pass_id") else None
    if key is None or "pass" not in key:
        return "none"
    p = key["pass"]
    if p.get("through_ball") or _snake((p.get("technique") or {}).get("name")) == "through_ball":
        return "through_ball"
    if p.get("cut_back"):
        return "cut_back"
    if p.get("cross"):
        return "cross"
    height = _snake((p.get("height") or {}).get("name"))
    return {"ground_pass": "ground", "low_pass": "low", "high_pass": "high"}.get(height, "ground")


def is_modelled(event: dict) -> bool:
    """A shot the model is for: not a penalty (which has its own fixed rate) and not in a
    penalty shootout."""
    if event.get("type", {}).get("name") != "Shot" or event.get("period") == 5:
        return False
    return _snake(event["shot"].get("type", {}).get("name")) != "penalty"


def features(event: dict, events_by_id: dict) -> dict:
    """The features of one shot event (see the module docstring)."""
    shot = event["shot"]
    x, y = event["location"][0], event["location"][1]
    shooter = (x, y)
    frame = shot.get("freeze_frame") or []
    opponents = [f for f in frame if not f.get("teammate")]
    keeper = next((f for f in opponents if (f.get("position") or {}).get("name") == "Goalkeeper"), None)
    outfield = [f for f in opponents if f is not keeper]
    cone = (shooter, (GOAL_X, POST_LOW), (GOAL_X, POST_HIGH))
    in_cone = [f for f in frame if _in_triangle(tuple(f["location"][:2]), *cone)]

    def dist(a, b):
        return math.hypot(a[0] - b[0], a[1] - b[1])

    body = _snake((shot.get("body_part") or {}).get("name"))
    body = "head" if body == "head" else "foot" if body in ("right_foot", "left_foot") else "other"
    shot_type = _snake((shot.get("type") or {}).get("name"))
    technique = _snake((shot.get("technique") or {}).get("name"))
    pattern = _snake((event.get("play_pattern") or {}).get("name")).replace("from_", "").replace("regular_play", "regular")
    return {
        "distance": dist(shooter, GOAL_CENTRE),
        "angle": goal_angle(x, y),
        "under_pressure": float(bool(event.get("under_pressure"))),
        "first_time": float(bool(shot.get("first_time"))),
        "one_on_one": float(bool(shot.get("one_on_one"))),
        "open_goal": float(bool(shot.get("open_goal"))),
        "follows_dribble": float(bool(shot.get("follows_dribble"))),
        "defenders_in_cone": float(sum(1 for f in in_cone if not f.get("teammate") and f is not keeper)),
        "players_in_cone": float(len(in_cone)),
        # No keeper in the frame (an empty net): as far away as the pitch allows.
        "keeper_to_shooter": dist(shooter, keeper["location"]) if keeper else 120.0,
        "keeper_off_line": GOAL_X - keeper["location"][0] if keeper else 120.0,
        "keeper_off_centre": abs(keeper["location"][1] - 40.0) if keeper else 40.0,
        "nearest_defender": min((dist(shooter, f["location"]) for f in outfield), default=60.0),
        "body_part": body,
        "shot_type": shot_type if shot_type in SHOT_TYPES else "open_play",
        "technique": technique if technique in TECHNIQUES else "normal",
        "pattern": pattern if pattern in PATTERNS else "other",
        "assist": _assist(shot, events_by_id),
    }


def vector(f: dict) -> list[float]:
    """The features as numbers: numeric ones as they are, categories one-hot, in a fixed order."""
    out = [float(f[k]) for k in NUMERIC]
    for key, values in CATEGORICAL.items():
        out += [1.0 if f[key] == v else 0.0 for v in values]
    return out


def names() -> list[str]:
    return list(NUMERIC) + [f"{k}={v}" for k, values in CATEGORICAL.items() for v in values]
