"""Reading a scout's phrase as a concept (app/concepts.py), and filtering on it.

The evaluation runs the production reader on every phrase in tests/search_phrases.py, once
with keywords alone (the baseline) and once with the embedding model, and prints both:

    cd apps/api && pytest -s tests/test_concepts.py -k evaluation

The model tests skip when fastembed or the model is not available. Set NORTHSTAR_MODELS_DIR
to a directory holding the downloaded model, or let fastembed download it (about 240 MB).

History, so the numbers are read correctly
------------------------------------------
- The model alone, reading whole phrases, lost to keywords on the tune half (53/76 against
  62/76). It reads single short words badly: Arabic names sat closest to the "potential"
  description at 0.66 to 0.77. So the model only ever reads what is left of a phrase after
  keywords, and only when that is two words or more.
- The threshold, 0.60, was chosen on the tune half with that design, as the one with the
  fewest phrases read as the wrong concept among those with the most right.
- The first held-out run, before the reader was wired into the search: keywords 51/61, with
  the model 54/61. It also showed that "height" was a keyword for tall, so "below average
  height" read as tall; it was removed. The numbers printed now are the production reader,
  after that fix and after merging in the search's earlier "no data" word list.
- The table tennis rating ("highly rated", "beats strong opponents") was added on 2026-10-08,
  with 13 labelled phrases written before its descriptions. Before it: tune 73/83 with the
  model (3 wrong concepts), held out 58/65 (1). After: tune 80/90 (3), held out 62/69 (1);
  no earlier phrase changed reading, and the model read all four held-out rating phrases right
  (keywords alone missed the Arabic one). Two-word keywords came with it, because "strong"
  alone already meant physical strength (no data). A first version also kept one-word
  keywords next to a two-word one, which read "wins against stronger players" as both the
  rating and "wins most matches" and pushed the tune half to 4 wrong; a two-word keyword is now
  the whole reading of its phrase.
- One caveat these numbers cannot remove: the phrases, the keywords, the descriptions and
  the filler words were all written by the same person, so the evaluation is kinder than real
  scouts would be.
"""

from __future__ import annotations

import os
import uuid
from datetime import timedelta

import pytest

from app import concepts
from tests.search_phrases import CROSS_SPORT, PHRASES, half


def _expected_kind(label: str) -> str:
    return label


def _predicted(reading: concepts.Reading) -> str:
    """One label per phrase, the way PHRASES is labelled."""
    ids = [c.id for c, _, _ in reading.concepts]
    if not ids:
        return "name" if reading.leftover else "nothing"
    labels = {"no_data" if i.startswith("no_data") else i for i in ids}
    return labels.pop() if len(labels) == 1 else "mixed"


def _wrong_concepts(reading: concepts.Reading, label: str) -> int:
    return sum(1 for c, _, _ in reading.concepts if c.answerable and c.id != label)


def _evaluate(reader, which: str) -> tuple[int, int, int, list[str]]:
    right = wrong = 0
    misses = []
    pool = {p: l for p, l in PHRASES.items() if half(p) == which}
    for phrase, label in pool.items():
        reading = concepts.read(concepts.WORD.findall(phrase), reader)
        got = _predicted(reading)
        right += got == label
        wrong += _wrong_concepts(reading, label)
        if got != label:
            misses.append(f"{phrase!r}: want {label}, got {got}")
    return right, len(pool), wrong, misses


@pytest.fixture(scope="module")
def reader():
    pytest.importorskip("fastembed")
    loaded = concepts.get_reader()
    if loaded is None:
        pytest.skip("the embedding model could not be loaded (offline, or not downloaded)")
    return loaded


@pytest.mark.parametrize("which", ["tune", "held out"])
def test_evaluation_keywords_alone(which):
    right, total, wrong, misses = _evaluate(None, which)
    print(f"\nkeywords alone, {which}: {right}/{total} right, {wrong} read as the wrong concept")
    for miss in misses:
        print("   ", miss)
    assert right / total >= {"tune": 0.80, "held out": 0.80}[which]


@pytest.mark.parametrize("which", ["tune", "held out"])
def test_evaluation_with_the_model(reader, which):
    right, total, wrong, misses = _evaluate(reader, which)
    print(f"\nwith the model, {which}: {right}/{total} right, {wrong} read as the wrong concept")
    for miss in misses:
        print("   ", miss)
    baseline, _, _, _ = _evaluate(None, which)
    # Held, so a change that makes the model worse than keywords cannot pass quietly.
    assert right >= baseline
    assert wrong <= 3


@pytest.mark.parametrize("use_model", [False, True])
def test_a_football_phrase_is_never_read_as_a_table_tennis_statistic(request, use_model):
    """Read as anything else, or as a name, is a miss; read as a table tennis statistic, it
    would filter a football search down to table tennis players and say it had helped."""
    reader = request.getfixturevalue("reader") if use_model else None
    table_tennis = {c.id for c in concepts.stat_concepts() if c.sports == ("table_tennis",)}
    for phrase in CROSS_SPORT:
        reading = concepts.read(concepts.WORD.findall(phrase), reader)
        assert not {c.id for c, _, _ in reading.concepts} & table_tennis, phrase


def test_names_never_reach_the_model_alone(reader):
    """One word left over always goes to name search, whatever the model would say."""
    for name in ("Kandil", "الشناوي", "كريم", "Ziad"):
        reading = concepts.read([name], reader)
        assert reading.concepts == [] and reading.leftover == [name]


def test_a_concept_phrase_does_not_search_its_other_words_as_names():
    reading = concepts.read(["physically", "small"], None)
    assert [c.id for c, _, _ in reading.concepts] == ["small_for_age"]
    assert reading.leftover == [] and reading.unused == ["physically"]


def test_filler_is_not_searched_as_a_name():
    reading = concepts.read(concepts.WORD.findall("small for his age"), None)
    assert [c.id for c, _, _ in reading.concepts] == ["small_for_age"]
    assert reading.leftover == []


def test_stat_concepts_come_from_the_sport_modules():
    ids = {c.id: c for c in concepts.stat_concepts()}
    assert ids["goals_per_90"].sports == ("football",)
    assert ids["match_win_rate"].sports == ("table_tennis",)
    assert "goals" in ids["goals_per_90"].keywords


def test_a_new_sport_brings_its_own_search_concepts(tmp_path):
    """The config-change claim, for search: a module nobody wrote code for."""
    import json
    import shutil

    from app import sports

    for existing in sports.default_modules_dir().glob("*.json"):
        shutil.copy(existing, tmp_path / existing.name)
    (tmp_path / "squash.json").write_text(
        json.dumps(
            {
                "sport": "squash",
                "label": "Squash",
                "roles": {"label": "Style", "values": ["attacking", "defensive"]},
                "usesTier": False,
                "periods": {
                    "squash.match.v1": {
                        "periodType": "match",
                        "label": "Matches",
                        "schema": {
                            "type": "object",
                            "required": ["games_won", "games_lost"],
                            "additionalProperties": False,
                            "properties": {
                                "games_won": {"type": "integer", "minimum": 0},
                                "games_lost": {"type": "integer", "minimum": 0},
                            },
                        },
                        "derived": [
                            {
                                "key": "game_win_rate",
                                "label": "Games won",
                                "numerator": ["games_won"],
                                "denominator": ["games_won", "games_lost"],
                                "search": {
                                    "better": "higher",
                                    "minBasis": 3,
                                    "describe": ["wins most of his games"],
                                    "keywords": ["unbeatable"],
                                },
                            }
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    modules = sports.registry(str(tmp_path))
    found = {c.id: c for c in concepts.stat_concepts(modules)}
    assert found["game_win_rate"].sports == ("squash",)


def test_a_searchable_stat_must_say_what_asking_for_it_sounds_like(tmp_path):
    import json

    from app import sports

    module = {
        "sport": "squash",
        "label": "Squash",
        "roles": {"label": "Style", "values": ["attacking"]},
        "usesTier": False,
        "periods": {
            "squash.match.v1": {
                "periodType": "match",
                "label": "Matches",
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"games_won": {"type": "integer"}},
                },
                "derived": [
                    {
                        "key": "wins",
                        "label": "Wins",
                        "numerator": ["games_won"],
                        "denominator": ["games_won"],
                        "search": {"better": "higher", "minBasis": 1},
                    }
                ],
            }
        },
    }
    path = tmp_path / "squash.json"
    path.write_text(json.dumps(module), encoding="utf-8")
    with pytest.raises(sports.ModuleError, match="describe"):
        sports.load_module(path)


# ---------------------------------------------------------------------------
# Through the search endpoint
# ---------------------------------------------------------------------------


@pytest.fixture
def squad(db, world):
    """Twelve boys of 14 with known heights and sprint times, so the percentiles are known.

    Measured today, so they are the latest reading. The seeded dataset may add to the
    cohort, which is why assertions compare the extremes, not exact cut-offs.
    """
    from app.models.measurement import Measurement
    from app.models.player import Player
    from tests.conftest import TODAY, grant_analytics

    rows = []
    for i in range(12):
        player = Player(
            id=uuid.uuid4(),
            full_name=f"Concept Boy {i}",
            date_of_birth=TODAY - timedelta(days=int(14.2 * 365.25)),
            sex="male",
            nationality=["EG"],
            is_egypt_eligible=True,
            primary_sport="football",
            tier="youth",
            position="CM",
            is_minor=True,
            status="active",
        )
        db.add(player)
        db.flush()
        grant_analytics(db, player)
        for metric, value in (("height_cm", 120 + i * 6), ("sprint_10m_s", 1.5 + i * 0.1)):
            db.add(
                Measurement(
                    id=uuid.uuid4(),
                    player_id=player.id,
                    measured_at=TODAY,
                    metric=metric,
                    value=value,
                    unit="cm" if metric == "height_cm" else "s",
                    source="coach_logged",
                )
            )
        rows.append(player)
    db.flush()
    from app.services import cohort

    cohort.reset_cache()
    return rows


def _search(client, auth, query: str) -> dict:
    return client.post(
        "/search",
        json={"query": query, "limit": 200, "includeMinors": True},
        headers=auth("admin"),
    ).json()


def test_small_for_age_filters_on_the_height_percentile(client, auth, squad):
    body = _search(client, auth, "small for his age")
    found = {r["player"]["id"] for r in body["results"]}
    assert str(squad[0].id) in found  # 120 cm at 14
    assert str(squad[-1].id) not in found  # 186 cm at 14
    labels = [c["label"] for c in body["parsed"]["chips"]]
    assert any(label.startswith("height: bottom quarter") for label in labels)


def test_fast_means_a_low_sprint_time(client, auth, squad):
    body = _search(client, auth, "fast")
    found = {r["player"]["id"] for r in body["results"]}
    assert str(squad[0].id) in found  # 1.5 s
    assert str(squad[-1].id) not in found  # 2.6 s


def test_a_no_data_ask_changes_nothing(client, auth, squad):
    everyone = _search(client, auth, "")["total"]
    body = _search(client, auth, "left footed")
    assert body["total"] == everyone
    chips = body["parsed"]["chips"]
    assert [c["label"] for c in chips] == ["preferred foot: no data", "left: not used"]
    assert not any(c["understood"] for c in chips)


def test_a_player_account_cannot_filter_on_flags(client, auth, squad):
    """Players do not see the models' flags, so they cannot search by one either."""
    body = client.post(
        "/search", json={"query": "late bloomer"}, headers=auth("player_self")
    ).json()
    chips = body["parsed"]["chips"]
    assert chips and all(chip["understood"] is False for chip in chips)
