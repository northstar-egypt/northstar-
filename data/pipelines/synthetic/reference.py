"""Reference data: organizations, positions, countries, name handling.

Kept apart from the generators so the vocabulary the dataset draws on is easy to
review and extend without touching generation logic.
"""

from __future__ import annotations

# Country codes follow config.COUNTRY_CODE_STANDARD (alpha-2 today). apps/web
# currently expects alpha-3; there is a board item to settle it in
# docs/schema.md. Every code the generator emits comes from this module, so the
# flip is contained here.
EGYPT = "EG"

# Where the diaspora tier actually plays: the leagues with Egyptian-eligible
# players in real life.
DIASPORA_COUNTRIES = ["GB", "FR", "DE", "IT", "NL", "BE", "SA", "AE", "QA", "US", "CA"]

CLUB_NAME_PARTS_AR = [
    "الأهلي",
    "الزمالك",
    "بيراميدز",
    "المصري",
    "الإسماعيلي",
    "سموحة",
    "إنبي",
    "المقاولون العرب",
    "طلائع الجيش",
    "سيراميكا",
    "البنك الأهلي",
    "فاركو",
    "غزل المحلة",
    "الاتحاد السكندري",
    "بلدية المحلة",
    "الجونة",
]

ACADEMY_NAME_PARTS_AR = [
    "أكاديمية النيل",
    "أكاديمية وادي دجلة",
    "أكاديمية المستقبل",
    "أكاديمية الصفوة",
    "أكاديمية النصر",
    "أكاديمية الشروق",
    "أكاديمية الجزيرة",
    "أكاديمية طيبة",
    "أكاديمية الدلتا",
    "أكاديمية الأقصر",
    "أكاديمية بورسعيد",
    "أكاديمية أسوان",
]

FOREIGN_CLUB_NAMES = [
    "Olympique Nord",
    "FC Rheinstadt",
    "Riverbank United",
    "AC Litorale",
    "Stade Atlantique",
    "SV Hafen",
    "Northgate City",
    "Union Vallée",
    "Al Sahra SC",
    "Coastline FC",
]

FEDERATION_NAMES = [
    ("الاتحاد المصري لكرة القدم", "football"),
    ("الاتحاد المصري لتنس الطاولة", "table_tennis"),
]

NATIONAL_TEAM_SUFFIXES = ["A", "U23", "U20", "U17"]

# Football positions, with the share of a squad each occupies.
FOOTBALL_POSITIONS = [
    ("GK", 0.09),
    ("CB", 0.16),
    ("LB", 0.07),
    ("RB", 0.07),
    ("CDM", 0.10),
    ("CM", 0.14),
    ("CAM", 0.09),
    ("LW", 0.08),
    ("RW", 0.08),
    ("ST", 0.12),
]

TABLE_TENNIS_STYLES = ["attacker", "all_round", "defender", "chopper"]

# Actions that show up in the audit log. The integrity board reads this table, so
# the vocabulary is the one it will filter on.
AUDIT_ACTIONS = [
    ("login.success", "User"),
    ("login.failure", "User"),
    ("player.create", "Player"),
    ("player.update", "Player"),
    ("player.merge", "Player"),
    ("measurement.create", "Measurement"),
    ("performance.import", "PerformanceEntry"),
    ("search.run", None),
    ("consent.grant", "Consent"),
    ("consent.revoke", "Consent"),
    ("export.request", "Player"),
]

# ---------------------------------------------------------------------------
# Arabic name variants, used to build realistic duplicate identities.
#
# Duplicate records in Egyptian youth data are rarely exact copies. They are the
# same human typed twice by two people, and the difference is orthographic:
# hamza written or dropped, taa marbuta typed as haa, final yaa as alef maqsura,
# a stray double space. A duplicate detector that only catches exact matches will
# score perfectly on naive data and fail here, which is the point.
# ---------------------------------------------------------------------------

_ORTHOGRAPHIC_SUBSTITUTIONS = [
    ("أ", "ا"),
    ("إ", "ا"),
    ("آ", "ا"),
    ("ة", "ه"),
    ("ي", "ى"),
    ("ؤ", "و"),
    ("ئ", "ى"),
]


def orthographic_variant(name: str, rng) -> str:
    """Return a plausible alternative spelling of an Arabic name.

    Applies one or two of the substitutions above where they apply. If none
    apply (the name has no ambiguous characters), falls back to a doubled space,
    which is the other way the same name gets typed twice.
    """
    applicable = [(a, b) for a, b in _ORTHOGRAPHIC_SUBSTITUTIONS if a in name]
    if not applicable:
        parts = name.split(" ")
        if len(parts) > 1:
            idx = rng.randint(1, len(parts) - 1)
            return " ".join(parts[:idx]) + "  " + " ".join(parts[idx:])
        return name + " "
    for a, b in rng.sample(applicable, rng.randint(1, min(2, len(applicable)))):
        name = name.replace(a, b, 1)
    return name


def drop_middle_name(name: str, rng) -> str:
    """Egyptian names carry the father's and grandfather's names.

    One clerk types all four, the next types two. Same person, different string.
    """
    parts = name.split()
    if len(parts) <= 2:
        return name
    keep = [parts[0]] + parts[2:] if rng.chance(0.5) else parts[:-1]
    return " ".join(keep)
