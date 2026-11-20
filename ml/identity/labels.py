"""Real labels for the identity engine: pairs a person has checked, and what they say.

The engine is graded on generated data (ml/run_identity_eval.py). On real data there were no
labelled pairs, only a count of certain mistakes (two StatsBomb records). This module is how
real labels are made and used:

1. **Anchors** (`anchors`), with no person involved: a FootyStats and a StatsBomb record with
   the same full name, at least two words, and that name held by one record in each source.
   Almost all are the same player. They are selected on the name alone, so they can measure
   how a true pair behaves on the other fields (`fit_m` uses them for nationality and club),
   and how many of them the engine links: a recall check on real data. Not a precision check:
   they are the easy pairs by construction.
2. **A labelled sample** (`sample`, `score`). Candidate pairs are split into strata by what the
   engine made of them, a random sample is drawn from each, and a person marks each pair "yes",
   "no" or "unsure" without seeing the engine's score. Weighting each stratum by its size gives
   precision and recall on real data, with bootstrap intervals.
3. **Board decisions** (`board_decisions`): every duplicate case a reviewer confirmed or
   dismissed on the integrity board. Reviewers choose which cases to decide, so these are not a
   random sample; they are reported beside the estimate, not mixed into it.

The sample file holds real players' names. It is written outside the repository, and this
module refuses to write it anywhere git could track.
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
import unicodedata
from collections import defaultdict
from datetime import date
from pathlib import Path

from ml.identity import engine

# ---------------------------------------------------------------------------
# 1. Anchors
# ---------------------------------------------------------------------------


def _source(player: dict) -> str:
    ids = player.get("external_ids") or {}
    return next((k for k in ("statsbomb", "footystats") if k in ids), "register")


def _plain(name: str | None) -> str:
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower().replace("-", " ")
    return " ".join(text.split())


def anchors(tables: dict[str, list[dict]]) -> list[tuple[str, str]]:
    """(FootyStats id, StatsBomb id) pairs with the same full name of two words or more, the
    name held by exactly one record in each source. Merged records are left out."""
    by: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for p in tables.get("players", []):
        if p.get("status") == "merged":
            continue
        by[_source(p)][_plain(p.get("full_name"))].append(p["id"])
    out = []
    for name, fs in by["footystats"].items():
        sb = by["statsbomb"].get(name, [])
        if len(name.split()) >= 2 and len(fs) == 1 and len(sb) == 1:
            out.append((fs[0], sb[0]))
    return sorted(out)


# ---------------------------------------------------------------------------
# 2. The labelled sample
# ---------------------------------------------------------------------------

# Strata, by what the engine made of a pair. Links are the pairs the engine proposes
# (`engine.propose`); the rest are split by how much of the name agreed, because that is where a
# missed true pair can be. Pairs sharing less than most of the name after the given name are
# not sampled: they are taken to be different people, and recall is measured over the strata.
STRATA = (
    ("linked-strong", "proposed, probability 0.9 or more"),
    ("linked-weak", "proposed, probability under 0.9"),
    ("near-whole-name", "not proposed; the whole name after the given name matches, given name not different"),
    ("near-most-name", "not proposed; most of the name matches, or the whole name with a different given name"),
)
LINKED = ("linked-strong", "linked-weak")
PER_STRATUM = 50
SAMPLE_SEED = 20261121


def stratum(pair: engine.ScoredPair, proposed: set[tuple[str, str]]) -> str | None:
    key = tuple(sorted((pair.a, pair.b)))
    if key in proposed:
        return "linked-strong" if pair.probability >= 0.9 else "linked-weak"
    name, given = pair.levels.get("name"), pair.levels.get("given")
    if name in ("all", "all-one-word") and given != "different":
        return "near-whole-name"
    if name in ("all", "all-one-word", "most"):
        return "near-most-name"
    return None


def _pair_id(a: str, b: str) -> str:
    return hashlib.sha256("|".join(sorted((a, b))).encode()).hexdigest()[:12]


def _m_fingerprint() -> str:
    return hashlib.sha256(engine.M_FILE.read_bytes()).hexdigest()[:12] if engine.M_FILE.exists() else ""


def _describe(tables: dict[str, list[dict]]) -> dict[str, dict]:
    """What a person needs to decide, per player: names, birth date, nationality, position, the
    source and its id, and the seasons played with the team each season."""
    orgs = {o["id"]: o.get("name") for o in tables.get("organizations", [])}
    seasons: dict[str, set[str]] = defaultdict(set)
    for e in tables.get("performance_entries", []):
        start = str(e.get("period_start") or "")[:4]
        team = orgs.get(e.get("organization_id")) or ""
        if start:
            seasons[e["player_id"]].add(f"{start} {team}".strip())
    clubs: dict[str, set[str]] = defaultdict(set)
    for a in tables.get("affiliations", []):
        if orgs.get(a.get("organization_id")):
            clubs[a["player_id"]].add(orgs[a["organization_id"]])
    out = {}
    for p in tables.get("players", []):
        ids = p.get("external_ids") or {}
        out[p["id"]] = {
            "name": p.get("full_name") or "",
            "known_as": p.get("known_as") or "",
            "born": str(p.get("date_of_birth") or ""),
            "nationality": " ".join(p.get("nationality") or []),
            "position": p.get("position") or "",
            "source": ", ".join(f"{k} {v}" for k, v in sorted(ids.items())) or "register",
            "clubs": "; ".join(sorted(clubs.get(p["id"], set()))),
            "seasons": "; ".join(sorted(seasons.get(p["id"], set()))[:8]),
        }
    return out


COLUMNS = ["pair_id", "same_person", "notes"] + [
    f"{side}_{f}" for side in ("a", "b")
    for f in ("name", "known_as", "born", "nationality", "position", "source", "clubs", "seasons")
]


def sample(tables: dict[str, list[dict]], out_dir: Path, per_stratum: int = PER_STRATUM,
           seed: int = SAMPLE_SEED) -> dict:
    """Draw the sample and write `pairs.csv` (for the person, with no engine score in it) and
    `sample.json` (the strata and their sizes, for scoring) to `out_dir`, outside the repo."""
    from ml.export_db import tracked_by_git

    if tracked_by_git(out_dir):
        raise ValueError(f"{out_dir} could be committed; the sample holds real players' names. "
                         f"Write it outside the repository.")
    active = {**tables, "players": [p for p in tables.get("players", []) if p.get("status") != "merged"]}
    records = engine.records_from_tables(active)
    scored, _ = engine.score(records)
    proposed = {tuple(sorted((s.a, s.b))) for s in engine.links_of(records, scored)}
    by_stratum: dict[str, list[engine.ScoredPair]] = defaultdict(list)
    for s in scored:
        k = stratum(s, proposed)
        if k:
            by_stratum[k].append(s)
    rng = random.Random(seed)
    chosen = []
    for k, _ in STRATA:
        pool = sorted(by_stratum[k], key=lambda s: _pair_id(s.a, s.b))
        chosen += [(k, s) for s in rng.sample(pool, min(per_stratum, len(pool)))]
    rng.shuffle(chosen)  # the person does not see which stratum a pair came from
    who = _describe(tables)
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "pairs.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for _, s in chosen:
            a, b = sorted((s.a, s.b))
            row = {"pair_id": _pair_id(a, b), "same_person": "", "notes": ""}
            for side, pid in (("a", a), ("b", b)):
                for f_, v in who[pid].items():
                    row[f"{side}_{f_}"] = v
            w.writerow(row)
    meta = {
        "created": date.today().isoformat(), "seed": seed, "per_stratum": per_stratum,
        "link": engine.LINK, "m_file": _m_fingerprint(),
        "strata": {k: {"about": about, "size": len(by_stratum[k])} for k, about in STRATA},
        "pairs": {_pair_id(s.a, s.b): {"stratum": k, "a": min(s.a, s.b), "b": max(s.a, s.b),
                                       "probability": round(s.probability, 4), "levels": s.levels}
                  for k, s in chosen},
    }
    (out_dir / "sample.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False) + "\n",
                                         encoding="utf-8", newline="\n")
    return meta


ANSWERS = {"yes": True, "y": True, "same": True, "no": False, "n": False, "different": False}


def read_labels(path: Path) -> dict[str, bool | None]:
    """pair id to True (same person), False (two people) or None (unsure or not yet labelled)."""
    out = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            out[row["pair_id"]] = ANSWERS.get((row.get("same_person") or "").strip().lower())
    return out


def _wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if not n:
        return 0.0, 1.0
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def _estimate(sizes: dict[str, int], answers: dict[str, list[bool]]) -> dict:
    share = {k: (sum(v) / len(v) if v else None) for k, v in answers.items()}
    if any(share.get(k) is None for k in sizes if sizes[k]):
        return {"precision": None, "recall": None}
    tp = sum(sizes[k] * share[k] for k in LINKED if sizes.get(k))
    fp = sum(sizes[k] * (1 - share[k]) for k in LINKED if sizes.get(k))
    fn = sum(sizes[k] * share[k] for k in sizes if k not in LINKED and sizes[k])
    return {"precision": tp / (tp + fp) if tp + fp else None, "recall": tp / (tp + fn) if tp + fn else None,
            "true_linked": tp, "wrong_linked": fp, "missed": fn}


def score(sample_dir: Path, reps: int = 2000, seed: int = 7) -> dict:
    """Precision and recall on real data from a labelled sample, each stratum weighted by its
    size, with 95% bootstrap intervals (labels resampled within each stratum)."""
    meta = json.loads((sample_dir / "sample.json").read_text(encoding="utf-8"))
    labels = read_labels(sample_dir / "pairs.csv")
    sizes = {k: v["size"] for k, v in meta["strata"].items()}
    answers: dict[str, list[bool]] = {k: [] for k in sizes}
    unsure = 0
    for pid, info in meta["pairs"].items():
        label = labels.get(pid)
        if label is None:
            unsure += 1
        else:
            answers[info["stratum"]].append(label)
    point = _estimate(sizes, answers)
    rng = random.Random(seed)
    boot = {"precision": [], "recall": []}
    for _ in range(reps):
        resampled = {k: [rng.choice(v) for _ in v] for k, v in answers.items()}
        e = _estimate(sizes, resampled)
        for m in boot:
            if e[m] is not None:
                boot[m].append(e[m])
    interval = {}
    for m, xs in boot.items():
        xs.sort()
        interval[m] = (xs[int(0.025 * len(xs))], xs[int(0.975 * len(xs)) - 1]) if xs else None
    per = {k: {"size": sizes[k], "labelled": len(v), "same": sum(v),
               "share": sum(v) / len(v) if v else None, "interval": _wilson(sum(v), len(v))}
           for k, v in answers.items()}
    return {"point": point, "interval": interval, "strata": per, "unsure_or_blank": unsure,
            "m_changed": meta.get("m_file") != _m_fingerprint()}


# ---------------------------------------------------------------------------
# 3. Board decisions
# ---------------------------------------------------------------------------


def board_decisions(database_url: str) -> dict[str, dict[str, int]]:
    """Decided duplicate cases on the integrity board, by detector: confirmed and dismissed."""
    from sqlalchemy import create_engine, text

    sql = text("select detector_name, status, count(*) from flag where type = 'duplicate' "
               "and status in ('confirmed', 'dismissed') group by 1, 2")
    out: dict[str, dict[str, int]] = defaultdict(lambda: {"confirmed": 0, "dismissed": 0})
    with create_engine(database_url, future=True).connect() as conn:
        for detector, status, n in conn.execute(sql):
            out[detector or "unknown"][status] = n
    return dict(out)
