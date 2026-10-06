"""Sport modules: the one place a sport is defined.

A sport is a JSON file in `packages/shared/sports/`. It says what a player's role is called
and which values it takes, whether the football tier applies, and, for each kind of
performance record (keyed by `PerformanceEntry.schema_ref`), which metrics exist, their
labels and units, the rules that make a record impossible, and the summary statistics worth
computing. Everything sport-specific in the product reads it from here: ingest validation,
the add-player screen, and the performance section of the player profile.

That is what makes the architecture's central claim testable. "Adding a sport is a config
change" means: drop a new file in that directory, and validation, logging and rendering work
for it with no code change. `tests/test_sports.py` does exactly that with a sport that exists
nowhere else in the repository.

Why not the `jsonschema` package
--------------------------------
Each module embeds a JSON Schema for its metrics, and a standard validator would read it. The
schemas use a small subset (object, required, additionalProperties false, integer, number,
boolean, string, minimum, maximum, enum), so this module validates that subset with the
standard library rather than adding a core dependency. It is strict about it: a module that
uses any keyword outside the subset is refused when it is loaded, so a schema can never
quietly mean more than is being checked. Swapping in `jsonschema` later is a change to
`_check_schema` alone.

Rules JSON Schema cannot express, such as "no more goals than shots", are the module's
`invariants`. There are four kinds, each generic enough to serve more than one sport:

  lte       [a, b]                       a <= b
  ifZero    field, thenZero: [fields]    if field is 0, every listed field is 0
  raceTo    [a, b], bestOf: field        a finished race: exactly one side reached
                                         best_of // 2 + 1 and the other did not
  atLeast   field, perUnit: f, value: n  field >= n * f

A derived statistic can also be made searchable, which lets a scout ask for it in words
("scoring well") on the search screen (app/concepts.py):

  "search": { "better": "higher" | "lower",
              "minBasis": n,                  records needed before a player counts
              "describe": ["...", ...],       what asking for it sounds like; needed once
                                              per statistic, in whichever period comes first
              "keywords": ["...", ...] }      single words that mean it on their own

A player matches when they are in the better quarter of their sport and tier for it.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from app.config import get_settings

_SCHEMA_KEYWORDS = {"type", "required", "additionalProperties", "properties"}
_PROPERTY_KEYWORDS = {"type", "minimum", "maximum", "enum", "title", "description", "x-unit"}
_TYPES = {
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float))
    and not isinstance(v, bool)
    and math.isfinite(v),
    "boolean": lambda v: isinstance(v, bool),
    "string": lambda v: isinstance(v, str),
}


class ModuleError(ValueError):
    """A sport module file is malformed. Raised at load, never at request time."""


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    unit: str | None


@dataclass(frozen=True)
class Period:
    schema_ref: str
    period_type: str
    label: str
    schema: dict
    invariants: list[dict]
    derived: list[dict]

    @property
    def metrics(self) -> list[Metric]:
        return [
            Metric(key, spec.get("title", key.replace("_", " ")), spec.get("x-unit"))
            for key, spec in self.schema["properties"].items()
        ]


@dataclass(frozen=True)
class SportModule:
    sport: str
    label: str
    role_label: str
    roles: list[str]
    uses_tier: bool
    # Each role in plain words ("CAM" -> "attacking midfielder"), for text written for people.
    # Optional; a role without one is shown as it is stored.
    role_names: dict[str, str] = field(default_factory=dict)
    # Which genders this sport registers. Players are only ever compared within one gender
    # (percentiles, growth curves, forecasts), so a sport open to both keeps them apart.
    genders: list[str] = field(default_factory=lambda: ["male", "female"])
    periods: dict[str, Period] = field(default_factory=dict)


def default_modules_dir() -> Path:
    configured = get_settings().sport_modules_dir
    if configured:
        return Path(configured)
    # apps/api/app/sports.py -> repository root -> packages/shared/sports
    return Path(__file__).resolve().parents[3] / "packages" / "shared" / "sports"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _check_schema(ref: str, schema: dict) -> None:
    unknown = set(schema) - _SCHEMA_KEYWORDS
    if unknown:
        raise ModuleError(f"{ref}: unsupported schema keywords {sorted(unknown)}")
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        raise ModuleError(
            f"{ref}: metrics must be an object with additionalProperties false, so an "
            f"unknown metric is rejected rather than stored unchecked"
        )
    properties = schema.get("properties") or {}
    if not properties:
        raise ModuleError(f"{ref}: no metrics defined")
    for key, spec in properties.items():
        unknown = set(spec) - _PROPERTY_KEYWORDS
        if unknown:
            raise ModuleError(f"{ref}.{key}: unsupported keywords {sorted(unknown)}")
        if spec.get("type") not in _TYPES:
            raise ModuleError(f"{ref}.{key}: type must be one of {sorted(_TYPES)}")
    for key in schema.get("required", []):
        if key not in properties:
            raise ModuleError(f"{ref}: required metric {key!r} is not defined")


def _check_fields(ref: str, rule: dict, names: list[str], properties: dict) -> None:
    for name in names:
        if name not in properties:
            raise ModuleError(f"{ref}: rule {rule} refers to undefined metric {name!r}")


def _check_rules(ref: str, schema: dict, invariants: list[dict], derived: list[dict]) -> None:
    properties = schema["properties"]
    for rule in invariants:
        if "lte" in rule:
            _check_fields(ref, rule, rule["lte"], properties)
        elif "ifZero" in rule:
            _check_fields(ref, rule, [rule["ifZero"], *rule["thenZero"]], properties)
        elif "raceTo" in rule:
            _check_fields(ref, rule, [*rule["raceTo"], rule["bestOf"]], properties)
        elif "atLeast" in rule:
            _check_fields(ref, rule, [rule["atLeast"], rule["perUnit"]], properties)
        else:
            raise ModuleError(f"{ref}: unknown invariant {rule}")
    for stat in derived:
        if "shareWhere" in stat:
            _check_fields(ref, stat, stat["shareWhere"]["gt"], properties)
        else:
            _check_fields(ref, stat, [*stat["numerator"], *stat["denominator"]], properties)
        search = stat.get("search")
        if search is not None:
            unknown = set(search) - {"better", "minBasis", "describe", "keywords"}
            if unknown or search.get("better") not in ("higher", "lower"):
                raise ModuleError(
                    f"{ref}.{stat['key']}: search takes better (higher or lower), minBasis, "
                    f"describe and keywords, got {sorted(search)}"
                )
            keywords = search.get("keywords", [])
            if not isinstance(keywords, list) or not all(
                isinstance(k, str) and k and " " not in k for k in keywords
            ):
                raise ModuleError(f"{ref}.{stat['key']}: search.keywords must be single words")
            if not isinstance(search.get("minBasis"), int) or search["minBasis"] < 1:
                raise ModuleError(f"{ref}.{stat['key']}: search.minBasis must be a whole number >= 1")
            describe = search.get("describe", [])
            if not isinstance(describe, list) or not all(isinstance(d, str) and d for d in describe):
                raise ModuleError(f"{ref}.{stat['key']}: search.describe must be a list of phrases")


def load_module(path: Path) -> SportModule:
    raw = json.loads(path.read_text(encoding="utf-8"))
    try:
        periods = {}
        for ref, spec in raw["periods"].items():
            _check_schema(ref, spec["schema"])
            _check_rules(ref, spec["schema"], spec.get("invariants", []), spec.get("derived", []))
            periods[ref] = Period(
                schema_ref=ref,
                period_type=spec["periodType"],
                label=spec["label"],
                schema=spec["schema"],
                invariants=spec.get("invariants", []),
                derived=spec.get("derived", []),
            )
        described = {
            stat["key"]
            for period in periods.values()
            for stat in period.derived
            if stat.get("search", {}).get("describe")
        }
        for period in periods.values():
            for stat in period.derived:
                if "search" in stat and stat["key"] not in described:
                    raise ModuleError(
                        f"{path.name}: {stat['key']} is searchable but no period describes "
                        f"what asking for it sounds like (search.describe)"
                    )
        return SportModule(
            sport=raw["sport"],
            label=raw["label"],
            role_label=raw["roles"]["label"],
            roles=list(raw["roles"]["values"]),
            uses_tier=bool(raw["usesTier"]),
            role_names=_role_names(path.name, raw["roles"]),
            genders=_genders(path.name, raw.get("genders", ["male", "female"])),
            periods=periods,
        )
    except KeyError as exc:
        raise ModuleError(f"{path.name}: missing {exc}") from exc


def _role_names(name: str, roles: dict) -> dict[str, str]:
    names = roles.get("names", {})
    unknown = set(names) - set(roles["values"])
    if unknown:
        raise ModuleError(f"{name}: roles.names has roles not in roles.values: {sorted(unknown)}")
    return dict(names)


_KNOWN_GENDERS = ("male", "female")


def _genders(name: str, values: list) -> list[str]:
    if not values or any(value not in _KNOWN_GENDERS for value in values):
        raise ModuleError(f"{name}: genders must be a non-empty list drawn from {_KNOWN_GENDERS}")
    return list(dict.fromkeys(values))


@lru_cache
def registry(modules_dir: str | None = None) -> dict[str, SportModule]:
    """Every sport module, by sport id. Cached: modules are read once per process."""
    directory = Path(modules_dir) if modules_dir else default_modules_dir()
    if not directory.is_dir():
        raise ModuleError(
            f"No sport modules at {directory}. Set SPORT_MODULES_DIR, or run from the repo."
        )
    modules = {}
    for path in sorted(directory.glob("*.json")):
        module = load_module(path)
        if module.sport in modules:
            raise ModuleError(f"sport {module.sport!r} is defined twice")
        modules[module.sport] = module
    return modules


def period_for(schema_ref: str, modules: dict[str, SportModule] | None = None) -> Period | None:
    for module in (modules or registry()).values():
        if schema_ref in module.periods:
            return module.periods[schema_ref]
    return None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate(
    metrics: dict, schema_ref: str, modules: dict[str, SportModule] | None = None
) -> list[str]:
    """Every reason these metrics cannot be a real record. Empty means valid."""
    period = period_for(schema_ref, modules)
    if period is None:
        return [f"no sport module defines {schema_ref!r}"]
    if not isinstance(metrics, dict):
        return ["metrics must be an object"]

    problems: list[str] = []
    properties = period.schema["properties"]
    for key in period.schema.get("required", []):
        if key not in metrics:
            problems.append(f"{key} is missing")
    for key, value in metrics.items():
        spec = properties.get(key)
        if spec is None:
            problems.append(f"{key} is not a {period.label.lower()} metric for this sport")
            continue
        if not _TYPES[spec["type"]](value):
            problems.append(f"{key} must be {spec['type']}")
            continue
        if "enum" in spec and value not in spec["enum"]:
            problems.append(f"{key} must be one of {spec['enum']}")
        if "minimum" in spec and value < spec["minimum"]:
            problems.append(f"{key} is below {spec['minimum']}")
        if "maximum" in spec and value > spec["maximum"]:
            problems.append(f"{key} is above {spec['maximum']}")
    if problems:
        # Cross-field rules assume every field is present and well typed. Checking them on a
        # record that already failed would report confusing knock-on errors.
        return problems

    for rule in period.invariants:
        if not _holds(rule, metrics):
            problems.append(rule.get("message", str(rule)))
    return problems


def impossibilities(
    metrics: dict, schema_ref: str, modules: dict[str, SportModule] | None = None
) -> list[str]:
    """Only the values that cannot be true: out of range, or breaking a cross-field rule.

    Narrower than `validate` on purpose. A missing metric, an unknown extra key or a value of
    the wrong type makes a record incomplete or badly formatted, which is a data-quality
    problem. A goal count above the shot count makes it impossible, which on a
    self-submitted record is an integrity problem. The fraud detector asks the second
    question, and asking the first instead would put fraud flags on partial imports.
    """
    period = period_for(schema_ref, modules)
    if period is None or not isinstance(metrics, dict):
        return []
    properties = period.schema["properties"]
    usable = {
        key: value
        for key, value in metrics.items()
        if key in properties and _TYPES[properties[key]["type"]](value)
    }
    problems = []
    for key, value in usable.items():
        spec = properties[key]
        if "enum" in spec and value not in spec["enum"]:
            problems.append(f"{key} must be one of {spec['enum']}")
        if "minimum" in spec and value < spec["minimum"]:
            problems.append(f"{key} is below {spec['minimum']}")
        if "maximum" in spec and value > spec["maximum"]:
            problems.append(f"{key} is above {spec['maximum']}")
    for rule in period.invariants:
        if not _holds(rule, usable):
            problems.append(rule.get("message", str(rule)))
    return problems


def _holds(rule: dict, m: dict) -> bool:
    # Optional metrics may be absent. A rule over an absent metric is not checked, rather
    # than being read as zero: reading a missing value as 0 is the bug the detector harness
    # already caught once (see ml/README.md).
    def present(*names: str) -> bool:
        return all(name in m for name in names)

    if "lte" in rule:
        a, b = rule["lte"]
        return not present(a, b) or m[a] <= m[b]
    if "ifZero" in rule:
        if not present(rule["ifZero"]) or m[rule["ifZero"]] != 0:
            return True
        return all(m.get(name, 0) == 0 for name in rule["thenZero"])
    if "raceTo" in rule:
        a, b = rule["raceTo"]
        if not present(a, b, rule["bestOf"]):
            return True
        target = m[rule["bestOf"]] // 2 + 1
        return sorted((m[a], m[b])) in ([x, target] for x in range(target))
    if "atLeast" in rule:
        if not present(rule["atLeast"], rule["perUnit"]):
            return True
        return m[rule["atLeast"]] >= rule["value"] * m[rule["perUnit"]]
    return False


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------


def summarise(period: Period, rows: list[dict]) -> list[dict]:
    """The period's derived statistics over a player's records.

    Ratios are pooled (total goals over total minutes), not averaged per record, so one
    ten-minute cameo with a goal cannot make a season look like a scoring streak. A statistic
    with a zero denominator is left out rather than reported as zero.
    """
    out = []
    for stat in period.derived:
        if "shareWhere" in stat:
            a, b = stat["shareWhere"]["gt"]
            usable = [r for r in rows if a in r and b in r]
            if not usable:
                continue
            value = sum(1 for r in usable if r[a] > r[b]) / len(usable)
            basis = len(usable)
        else:
            numerator = sum(r.get(k, 0) for r in rows for k in stat["numerator"])
            denominator = sum(r.get(k, 0) for r in rows for k in stat["denominator"])
            if not denominator:
                continue
            value = numerator / denominator * stat.get("scale", 1)
            basis = len(rows)
        out.append(
            {
                "key": stat["key"],
                "label": stat["label"],
                "value": value,
                "format": stat.get("format", "number"),
                "basis": basis,
            }
        )
    return out
