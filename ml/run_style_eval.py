"""Evaluate "plays most like" (ml/pro/style.py) on real half seasons. See ml/pro/style_eval.py.

    python -m ml.run_style_eval --data-dir D:/northstar-data/statsbomb

Each 2015/16 league season (Premier League, La Liga, Serie A, Ligue 1, StatsBomb open data) is
split at the date halfway through its matches; every player's two halves are aggregated with the
loader's own code (data/pipelines/statsbomb/aggregate.py), using StatsBomb's published xG. A
player's position group is read from the whole season. The data folder is outside the
repository (real players, decision 0008); the numbers are in ml/README.md, "Player similarity,
professionals".
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "apps" / "api")]

from app import sports  # noqa: E402
from data.pipelines.statsbomb import aggregate  # noqa: E402
from ml.pro import style_eval  # noqa: E402
from ml.pro.seasons import SeasonRow  # noqa: E402

LEAGUES = [("Premier League", "2015/2016"), ("La Liga", "2015/2016"), ("Serie A", "2015/2016"), ("Ligue 1", "2015/2016")]


def halves(data_dir: Path) -> tuple[list[SeasonRow], list[SeasonRow]]:
    comps = json.loads((data_dir / "competitions.json").read_text(encoding="utf-8"))
    first, second = [], []
    for name, season in LEAGUES:
        comp = next(c for c in comps if c["competition_name"] == name and c["season_name"] == season)
        matches = json.loads((data_dir / "matches" / str(comp["competition_id"]) / f"{comp['season_id']}.json")
                             .read_text(encoding="utf-8"))
        days = sorted(date.fromisoformat(m["match_date"]) for m in matches)
        cut = days[len(days) // 2]
        results = {"first": [], "second": []}
        for m in matches:
            mid = m["match_id"]
            events = json.loads((data_dir / "events" / f"{mid}.json").read_text(encoding="utf-8"))
            lineups = json.loads((data_dir / "lineups" / f"{mid}.json").read_text(encoding="utf-8"))
            half = "first" if date.fromisoformat(m["match_date"]) < cut else "second"
            results[half].append(aggregate.read_match(m, events, lineups))
        whole_positions: dict[int, dict[str, float]] = defaultdict(dict)
        totals = {}
        for half, rs in results.items():
            players, _, positions = aggregate.season_totals(rs)
            totals[half] = players
            for pid, spent in positions.items():
                aggregate.add(whole_positions[pid], spent)
        for half, target in (("first", first), ("second", second)):
            for pid, by_team in totals[half].items():
                # A player who changed club mid-season: their two halves are not one style's.
                if len(by_team) != 1:
                    continue
                (team, counts), = by_team.items()
                target.append(SeasonRow(str(pid), half, date(2016, 5, 31), name, str(team),
                                        aggregate.main_position(whole_positions[pid]), None,
                                        aggregate.player_season(counts), "statsbomb"))
        print(f"{name} {season}: split at {cut}", flush=True)
    return first, second


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", required=True, type=Path)
    args = parser.parse_args()
    config = sports.registry()["football"].team_gaps
    first, second = halves(args.data_dir)
    print(f"\nPlayers with {style_eval.MIN_HALF_MINUTES}+ minutes in both halves, by position group:\n")
    print("  group                 players  top 1   top 5   top 10  median rank   MRR     | random: top 1  top 5  top 10  median  MRR")
    for r in style_eval.evaluate(config, first, second):
        print(f"  {r.group:<21} {r.players:>7}  {r.top1:6.1%}  {r.top5:6.1%}  {r.top10:6.1%}  {r.median_rank:>11}  {r.mrr:.3f}"
              f"   |         {r.random_top1:5.1%}  {r.random_top5:5.1%}  {r.random_top10:5.1%}  {r.random_median_rank:6.1f}  {r.random_mrr:.3f}")


if __name__ == "__main__":
    main()
