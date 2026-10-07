"""Phrases a scout might type, labelled with what the search should read them as.

For scoring how the query box turns free text into something the platform can compute
(app/concepts.py). Written before the concept descriptions and before the threshold, from how
scouts and coaches talk, in English and Egyptian Arabic, so the model is judged on phrasings it
was not built around.

Labels:
  a concept id   the phrase asks for something the platform computes (see app/concepts.py)
  "no_data"      a real scouting ask the platform has no data for; it must change nothing
  "name"         not a concept at all; it must fall through to name search

The worst mistake is reading a phrase as a concept it is not, because that silently filters
the results. Reading a concept phrase as "no_data" only fails to help.

Split by `half()` like the name spellings: the threshold is chosen on "tune", and "held out"
is what gets reported.
"""

from __future__ import annotations

import hashlib

PHRASES: dict[str, str] = {
    # small for his age
    "small for his age": "small_for_age",
    "short for his age": "small_for_age",
    "undersized": "small_for_age",
    "physically small": "small_for_age",
    "tiny kid": "small_for_age",
    "hasn't grown yet": "small_for_age",
    "smaller than the other boys": "small_for_age",
    "below average height": "small_for_age",
    "short player": "small_for_age",
    "a bit small": "small_for_age",
    "قصير بالنسبة لسنه": "small_for_age",
    "جسمه صغير": "small_for_age",
    "قصير": "small_for_age",
    # tall for his age
    "tall for his age": "tall_for_age",
    "tall": "tall_for_age",
    "big lad": "tall_for_age",
    "very tall": "tall_for_age",
    "good height": "tall_for_age",
    "taller than his teammates": "tall_for_age",
    "physically big": "tall_for_age",
    "above average height": "tall_for_age",
    "tall kid": "tall_for_age",
    "طويل": "tall_for_age",
    "طويل بالنسبة لسنه": "tall_for_age",
    # fast
    "fast": "fast",
    "quick": "fast",
    "rapid": "fast",
    "pacey": "fast",
    "has pace": "fast",
    "good acceleration": "fast",
    "quick off the mark": "fast",
    "very fast over short distances": "fast",
    "explosive speed": "fast",
    "fast sprinter": "fast",
    "سريع": "fast",
    "عنده سرعة": "fast",
    # scoring rate (football)
    "scoring well": "goals_per_90",
    "scores a lot": "goals_per_90",
    "prolific": "goals_per_90",
    "goalscorer": "goals_per_90",
    "scores goals": "goals_per_90",
    "good goal record": "goals_per_90",
    "lots of goals": "goals_per_90",
    "high scoring": "goals_per_90",
    "a real goal threat": "goals_per_90",
    "top scorer": "goals_per_90",
    "هداف": "goals_per_90",
    "بيجيب أجوان كتير": "goals_per_90",
    # finishing (football)
    "clinical finisher": "shot_conversion",
    "clinical": "shot_conversion",
    "good finisher": "shot_conversion",
    "converts his chances": "shot_conversion",
    "efficient in front of goal": "shot_conversion",
    "does not waste chances": "shot_conversion",
    "good shot conversion": "shot_conversion",
    "finishes well": "shot_conversion",
    "لمسته الأخيرة حلوة": "shot_conversion",
    # passing (football)
    "good passer": "pass_completion",
    "accurate passing": "pass_completion",
    "rarely gives the ball away": "pass_completion",
    "keeps possession well": "pass_completion",
    "tidy on the ball": "pass_completion",
    "high pass completion": "pass_completion",
    "reliable passer": "pass_completion",
    "pinpoint passing": "pass_completion",
    "تمريراته دقيقة": "pass_completion",
    "بيحافظ على الكورة": "pass_completion",
    # winning matches (table tennis)
    "wins most of his matches": "match_win_rate",
    "wins a lot": "match_win_rate",
    "winning record": "match_win_rate",
    "good win rate": "match_win_rate",
    "rarely loses": "match_win_rate",
    "winner": "match_win_rate",
    "strong results": "match_win_rate",
    "beats most opponents": "match_win_rate",
    "بيكسب معظم ماتشاته": "match_win_rate",
    # serve and unforced errors (table tennis). Added with those statistics, after a first
    # draft of their descriptions read two football phrases above as unforced errors, and
    # before the model had read these.
    "good serve": "service_winners_per_set",
    "wins points on his serve": "service_winners_per_set",
    "his serve is a weapon": "service_winners_per_set",
    "lots of service aces": "service_winners_per_set",
    "dangerous server": "service_winners_per_set",
    "إرساله حلو": "service_winners_per_set",
    "few unforced errors": "unforced_errors_per_set",
    "doesn't make many errors": "unforced_errors_per_set",
    "rarely makes errors": "unforced_errors_per_set",
    "low error rate": "unforced_errors_per_set",
    "أخطاؤه قليلة": "unforced_errors_per_set",
    # strong against other players (the table tennis rating). Written with the concept, before
    # its descriptions and before the model had read any of them. Two of these contain a word
    # that is already a keyword for something else ("wins", "strong"), on purpose: that is how
    # scouts will say it, and a miss there should show.
    "beats strong opponents": "rating_high",
    "highly rated": "rating_high",
    "high rating": "rating_high",
    "top rated": "rating_high",
    "one of the strongest players": "rating_high",
    "plays well against good opponents": "rating_high",
    "wins against stronger players": "rating_high",
    "handles tough opposition": "rating_high",
    "best ranked": "rating_high",
    "تصنيفه عالي": "rating_high",
    "بيغلب اللاعبين الأقوياء": "rating_high",
    # late bloomer
    "late bloomer": "late_bloomer",
    "late developer": "late_bloomer",
    "still to hit his growth spurt": "late_bloomer",
    "will grow later": "late_bloomer",
    "late maturing": "late_bloomer",
    "developing late": "late_bloomer",
    "physically behind but catching up": "late_bloomer",
    "هيطول متأخر": "late_bloomer",
    # asks the platform cannot answer
    "left footed": "no_data",
    "right footed": "no_data",
    "two footed": "no_data",
    "strong": "no_data",
    "physically strong": "no_data",
    "good in the air": "no_data",
    "good header of the ball": "no_data",
    "great attitude": "no_data",
    "hard working": "no_data",
    "leader": "no_data",
    "good character": "no_data",
    "high potential": "no_data",
    "future star": "no_data",
    "good dribbler": "no_data",
    "good vision": "no_data",
    "calm under pressure": "no_data",
    "injury free": "no_data",
    "brave": "no_data",
    "good xg": "no_data",
    "good first touch": "no_data",
    "بيلعب بالشمال": "no_data",
    "أخلاقه كويسة": "no_data",
    "قوي بدنيا": "no_data",
    # names, which must fall through to name search
    "Mohamed": "name",
    "Ahmed Hassan": "name",
    "Mostafa": "name",
    "Karim": "name",
    "Youssef": "name",
    "El-Shenawy": "name",
    "Abdelrahman": "name",
    "Hegazy": "name",
    "Salah": "name",
    "Ziad": "name",
    "Kandil": "name",
    "Marwan": "name",
    "Tarek": "name",
    "Omar Khaled": "name",
    "Fares": "name",
    "Nour": "name",
    "Yasmin": "name",
    "Malak": "name",
    "Habiba": "name",
    "Mazen": "name",
    "Seif": "name",
    "Hesham": "name",
    "محمد": "name",
    "أحمد حسن": "name",
    "كريم": "name",
    "الشناوي": "name",
    "مروان": "name",
    "سلمى": "name",
    "فارس": "name",
    "نور": "name",
}


# Football phrases that sit next to the table tennis statistics: keeping the ball, not wasting
# chances. Not scored above, because they test something else: whatever they are read as, it
# must never be a table tennis statistic, which would silently turn a football search into a
# table tennis one. A first draft of the unforced-errors description did exactly that to "tidy
# on the ball" and "does not waste chances".
CROSS_SPORT: list[str] = [
    "doesn't lose the ball",
    "never wastes a chance",
    "keeps possession well",
    "tidy on the ball",
    "does not waste chances",
    "rarely gives the ball away",
    "a consistent passer",
]


def half(phrase: str) -> str:
    digest = hashlib.sha256(phrase.encode("utf-8")).digest()
    return "tune" if digest[0] % 2 == 0 else "held out"


# The baseline the model has to beat: a keyword list of the kind the parser already uses for
# "no data" terms, extended with the obvious word for each concept. Written at the same time
# as the phrases above, before any model output was seen. A phrase is read as the first
# concept one of whose keywords it contains as a whole word; otherwise as a name.
BASELINE_KEYWORDS: dict[str, list[str]] = {
    "small_for_age": ["small", "short", "undersized", "tiny", "قصير", "صغير"],
    "tall_for_age": ["tall", "height", "big", "طويل"],
    "fast": ["fast", "quick", "pace", "pacey", "speed", "rapid", "سريع", "سرعة"],
    "goals_per_90": ["goals", "scoring", "scorer", "scores", "prolific", "goalscorer", "هداف", "أجوان"],
    "shot_conversion": ["clinical", "finisher", "finishing", "conversion"],
    "pass_completion": ["passer", "passing", "passes", "possession", "تمريراته"],
    "match_win_rate": ["wins", "winning", "winner", "win"],
    "service_winners_per_set": ["serve", "server", "service", "إرساله"],
    "unforced_errors_per_set": ["unforced", "errors", "أخطاؤه"],
    "late_bloomer":["late", "bloomer", "متأخر"],
    "rating_high": ["rated", "rating", "ranked", "strongest", "تصنيفه"],
    "no_data": [
        "footed", "foot", "strong", "strength", "header", "air", "attitude", "working",
        "leader", "character", "potential", "star", "dribbler", "vision", "pressure",
        "injury", "brave", "xg", "touch", "بالشمال", "أخلاقه", "قوي",
    ],
}
