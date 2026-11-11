"""The assistant's second reader: fixed rules, for when the language model is not running.

The assistant (services/assistant.py) has a local model read a question into a fixed form and
then answers from the platform's own services. The model is the one part that can be missing:
Ollama not started, a laptop with no GPU where it is slow, a demo machine where it will not
load. This module fills in the same form with word lists and patterns instead, so the Ask
screen still answers, and says on screen that it read the question by rule.

It returns the raw form the model would return. The assistant then cleans it with the same
`_clean` and applies the same age and flag-list rules as a model reading, so whatever the
rules get wrong is caught by the same checks and shown in the same "How this was read" chips.

The word lists come from the field descriptions in the model's prompt (SYSTEM_PROMPT in
services/assistant.py) and the development questions in eval/assistant_questions.json. The
held-out questions were not read while writing them. How often it reads right is measured by
`python -m eval.run_assistant_eval --reader rules`; the numbers are in ml/README.md,
"Assistant".

What it cannot do that the model can: a name written in lower case or as a single word
("is karim injured"), and phrasings outside its lists. Those come back as "I can answer four
kinds of question", which is a refusal, not a wrong answer.
"""

from __future__ import annotations

import re

_I = re.IGNORECASE


def _any(*patterns: str, flags: int = _I) -> re.Pattern:
    return re.compile("|".join(f"(?:{p})" for p in patterns), flags)


# Questions the records cannot answer. Checked first: "Omar Hassan's salary" names a player,
# and is still not a question about his match record.
UNSUPPORTED = _any(
    r"\bsalar(y|ies)\b", r"\bwages?\b", r"\bcontracts?\b", r"\btransfers?\b", r"\bmarket value\b",
    r"\binjur", r"\bhurt\b", r"\bfit to play\b", r"\bnational team\b", r"\bsign(ing)?\b",
    r"\bshould\b", r"\bwill\b", r"\bpredict", r"\bnews\b", r"\bbuy\b", r"\bcost\b",
    r"مرتب", r"راتب", r"عقد", r"انتقال", r"إصاب", r"اصاب", r"مصاب", r"منتخب",
)

# The order matters: the specific phrase before the general word it contains ("passing
# accuracy" before "passing", "key passes" before "passes", "chances created" before nothing).
STATISTICS: list[tuple[str, re.Pattern]] = [
    ("pass_completion", _any(
        r"\bpass(ing)? (accuracy|completion)\b", r"\baccura(te|cy)\b", r"\bbest pass(er|ers)\b",
        r"\bcompletion\b", r"دقة التمرير", r"دقة التمريرات")),
    ("key_passes", _any(
        r"\bkey pass", r"\bchances?\b", r"\bcreat(e|es|ive|ivity|or|ors)\b", r"صناعة", r"فرص")),
    ("assists", _any(r"\bassists?\b", r"أسيست", r"اسيست", r"تمريرات? حاسم", r"صناعة أهداف")),
    ("goals", _any(
        r"\bgoals?\b", r"\bscor(e|er|ers|es|ing)\b", r"\bfinish(er|ers|ing)\b",
        r"هداف", r"أهداف", r"اهداف", r"جول")),
    ("shots", _any(r"\bshot", r"\bshoot", r"تسديد", r"تسديدات", r"شوت")),
    ("passes_attempted", _any(r"\bpass(es|er|ers|ing)?\b", r"تمرير", r"باص")),
    ("tackles", _any(
        r"\btackl", r"\bdefending\b", r"\bwin(s|ning)? (the )?ball\b", r"\bball[\s-]winn",
        r"افتكاك", r"قطع")),
    ("distance_km", _any(
        r"\brun(s|ning|ner|ners)?\b", r"\bdistance\b", r"\bwork[\s-]*rate\b", r"\bhard[\s-]*work",
        r"\bstamina\b", r"\bkilomet", r"\bkm\b", r"بيجري", r"جري", r"مجهود")),
    # Table tennis.
    ("service_winners", _any(r"\bserv(e|es|er|ers|ing|ice)\b", r"إرسال", r"ارسال")),
    ("unforced_errors", _any(
        r"\berrors?\b", r"\bmistakes?\b", r"\bconsisten(t|cy)\b", r"أخطاء", r"اخطاء", r"غلط")),
    ("set_share", _any(r"\bsets?\b", r"أشواط", r"اشواط", r"\bست\b")),
    ("point_share", _any(r"\bpoints?\b", r"نقاط", r"نقط")),
]

POSITIONS: list[tuple[str, re.Pattern]] = [
    ("goalkeeper", _any(r"\bgoal[\s-]*keepers?\b", r"\bkeepers?\b", r"\bgoalies?\b", r"حارس", r"حراس")),
    ("defender", _any(
        r"\bdefenders?\b", r"\b(centre|center|full|wing)[\s-]*backs?\b", r"\bfullbacks?\b",
        r"مدافع", r"دفاع", r"ظهير", r"قلب دفاع")),
    ("midfielder", _any(r"\bmidfield(er|ers)?\b", r"\bplaymakers?\b", r"لاعب وسط", r"وسط")),
    ("forward", _any(
        r"\bstrikers?\b", r"\bforwards?\b", r"\bwingers?\b", r"\battackers?\b",
        r"مهاجم", r"جناح", r"رأس حربة")),
]
# Position codes are capitals in the question ("CB", "ST"), so they are matched case-sensitively.
POSITION_CODES = {
    "GK": "goalkeeper", "CB": "defender", "LB": "defender", "RB": "defender",
    "CDM": "midfielder", "CM": "midfielder", "CAM": "midfielder",
    "ST": "forward", "LW": "forward", "RW": "forward",
}

TABLE_TENNIS = _any(r"\btable[\s-]*tennis\b", r"\bping[\s-]*pong\b", r"تنس طاولة", r"تنس الطاولة", r"بينج")
FOOTBALL = _any(r"\bfootball\b", r"\bsoccer\b", r"كرة القدم", r"كورة")
FEMALE = _any(r"\bgirls?\b", r"\bwom[ae]n\b", r"\bfemales?\b", r"\bladies\b", r"بنات", r"سيدات", r"لاعبات", r"ستات")
MALE = _any(r"\bboys?\b", r"\bm[ae]n\b", r"\bmales?\b", r"ولاد", r"رجال")

SIMILAR = _any(r"\blike\b", r"\bsimilar\b", r"\bresembl", r"\bplays? the same\b", r"زي", r"شبه", r"مثل")
LEADERS = _any(
    r"\bbest\b", r"\btop\b", r"\bmost\b", r"\bfewest\b", r"\bleast\b", r"\bhighest\b",
    r"\blowest\b", r"\bleaders?\b", r"\bwho\b", r"\bwhich\b",
    r"أحسن", r"احسن", r"أكتر", r"اكتر", r"أكثر", r"اكثر", r"أقل", r"اقل", r"مين")

# Latin names: two or more capitalised words in a row ("Karim Fathy Nour"). Capitalised words
# that start a question are not names and are dropped from the front of a run.
_LATIN_RUN = re.compile(r"(?:\b[A-Z][a-z]+(?:'s)?\b[ \t]*)+")
_NOT_NAMES = {
    "who", "what", "which", "how", "is", "are", "show", "compare", "find", "top", "best",
    "players", "player", "stats", "any", "most", "the", "me", "give", "list", "tell", "does",
    "do", "can", "will", "should", "and", "or", "vs", "versus", "between", "girls", "boys",
    "table", "tennis", "ping", "pong", "football", "strikers", "striker", "defenders",
    "midfielders", "goalkeepers", "wingers",
}

# Arabic has no capitals, so a name is read after a word that introduces one, up to the end
# or a word that ends it: "زي سيف ياسر شعبان", "قارن بين رامي باسم رياض و حسن جمال".
# The introducing word must be a whole word: "بين" is also the end of "لاعبين" (players).
_AR_INTRO = re.compile(
    r"(?:^|\s)(?:زي|شبه|مثل|بين|إحصائيات|احصائيات|أرقام|ارقام|مستوى|مستوي|قارن|عن)\s+(.+)")
_AR_STOP = re.compile(r"\s+(?:في|فى|على|علي|الموسم|ده|دي|السنة|من حيث|بالنسبة)\b.*")
_AR_SPLIT = re.compile(r"\s+(?:و|ولا|مع|أو|او)\s+|\s+و(?=\S)")
_ARABIC_WORD = re.compile(r"[؀-ۿ]+")


def _latin_names(question: str) -> list[str]:
    found = []
    for run in _LATIN_RUN.findall(question):
        words = [w.removesuffix("'s") for w in run.split()]
        while words and words[0].lower() in _NOT_NAMES:
            words.pop(0)
        while words and words[-1].lower() in _NOT_NAMES:
            words.pop()
        if len(words) >= 2:
            found.append(" ".join(words))
    return found


def _arabic_names(question: str) -> list[str]:
    match = _AR_INTRO.search(question)
    if not match:
        return []
    rest = _AR_STOP.sub("", match.group(1)).strip(" ؟?.!،,")
    rest = re.sub(r"^بين\s+", "", rest)
    found = []
    for part in _AR_SPLIT.split(rest):
        words = _ARABIC_WORD.findall(part)
        if len(words) >= 2:
            found.append(" ".join(words))
    return found


def _first(question: str, table: list[tuple[str, re.Pattern]]) -> str | None:
    for key, pattern in table:
        if pattern.search(question):
            return key
    return None


def read(question: str) -> dict:
    """The raw reading of one question, in the shape the model returns (READING_SCHEMA)."""
    players = _latin_names(question) + _arabic_names(question)
    statistic = _first(question, STATISTICS)
    position = _first(question, POSITIONS)
    if position is None:
        for code in re.findall(r"\b[A-Z]{2,3}\b", question):
            if code in POSITION_CODES:
                position = POSITION_CODES[code]
                break
    sport = "table_tennis" if TABLE_TENNIS.search(question) else (
        "football" if FOOTBALL.search(question) else None)
    gender = "female" if FEMALE.search(question) else ("male" if MALE.search(question) else None)

    if UNSUPPORTED.search(question):
        intent = "unsupported"
    elif len(players) >= 2:
        intent = "compare"
    elif len(players) == 1:
        intent = "similar" if SIMILAR.search(question) else "player"
    elif statistic or position or sport or gender or LEADERS.search(question):
        intent = "leaders"
    else:
        intent = "unsupported"
    # A statistic of the other sport than the one named is dropped by the assistant's _clean;
    # a table tennis question with a football word in it ("points" vs "passes") would otherwise
    # read the first match in the list.
    if sport == "table_tennis" and statistic not in (
        "service_winners", "unforced_errors", "set_share", "point_share"
    ):
        statistic = _first(question, STATISTICS[-4:])
    return {
        "intent": intent, "sport": sport, "gender": gender, "position_group": position,
        "age_from": None, "age_to": None, "statistic": statistic, "players": players,
    }
