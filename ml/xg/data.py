"""Non-penalty shots from StatsBomb's open data, as rows for the xG model.

Reads a folder laid out like StatsBomb's open-data `data/` directory, kept outside the
repository (real players, decision 0008). One match at a time; a cache file (also outside the
repository) makes reruns quick.
"""

from __future__ import annotations

import json
from pathlib import Path

from ml.xg import features as feats

TRAIN = [("Premier League", "2015/2016"), ("La Liga", "2015/2016"), ("Serie A", "2015/2016"), ("Ligue 1", "2015/2016")]
TEST = [("FIFA World Cup", "2018"), ("FIFA World Cup", "2022"), ("African Cup of Nations", "2023")]


def read(data_dir: Path, wanted: list[tuple[str, str]]) -> list[dict]:
    """One row per modelled shot: the match, the competition, its features, whether it was a goal,
    and StatsBomb's own xG for the same shot."""
    comps = json.loads((data_dir / "competitions.json").read_text(encoding="utf-8"))
    rows = []
    for name, season in wanted:
        comp = next(c for c in comps if c["competition_name"] == name and c["season_name"] == season)
        matches = json.loads((data_dir / "matches" / str(comp["competition_id"]) / f"{comp['season_id']}.json")
                             .read_text(encoding="utf-8"))
        for m in matches:
            path = data_dir / "events" / f"{m['match_id']}.json"
            if not path.exists():
                continue
            events = json.loads(path.read_text(encoding="utf-8"))
            by_id = {e["id"]: e for e in events}
            for e in events:
                if not feats.is_modelled(e):
                    continue
                rows.append({
                    "id": e["id"], "match": m["match_id"], "competition": f"{name} {season}",
                    "features": feats.features(e, by_id),
                    "goal": int(e["shot"]["outcome"]["name"] == "Goal"),
                    "statsbomb_xg": float(e["shot"].get("statsbomb_xg") or 0.0),
                })
    return rows


def load(data_dir: Path, cache: Path | None) -> tuple[list[dict], list[dict]]:
    """(train, test) rows, from the cache when it exists."""
    if cache is not None and cache.exists():
        saved = json.loads(cache.read_text(encoding="utf-8"))
        return saved["train"], saved["test"]
    train, test = read(data_dir, TRAIN), read(data_dir, TEST)
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"train": train, "test": test}), encoding="utf-8")
    return train, test
