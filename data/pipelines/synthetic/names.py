"""Egyptian names.

The review asked for `Faker("ar_EG")` instead of the default locale, because the
previous pass produced Egyptian players called Stephanie West and Todd Smith.
That instruction is right about the problem but the fix does not work on its own:
Faker's `ar_EG` locale ships no person provider, so `Faker("ar_EG").name()`
silently falls back to `en_US` and still returns Todd Smith. (Verified against
Faker 40: `Faker("ar_EG").get_providers()` resolves person to
`faker.providers.person.en_US`.)

`ar_AA` does have Arabic names, but they are pan-Arab and come with honorifics
and Gulf and Levantine family names that would look wrong in an Egyptian academy
register, and honorifics inside `full_name` would poison any name-matching the
duplicate detector does.

So the names come from curated Egyptian lists, registered as a Faker provider so
they still draw from the seeded Faker instance and stay reproducible.

Name shape follows Egyptian convention: given name, then the father's given name,
then optionally the grandfather's, then the family name. That structure is what
makes the duplicate cases realistic, because the commonest duplicate in a real
register is the same person entered once with three names and once with four.
"""

from __future__ import annotations

from faker.providers import BaseProvider

MALE_GIVEN = [
    "محمد", "أحمد", "محمود", "مصطفى", "خالد", "عمر", "يوسف", "كريم", "إسلام",
    "حسن", "حسين", "إبراهيم", "عبد الرحمن", "عبد الله", "طارق", "شريف", "هيثم",
    "ياسر", "سامح", "وليد", "رامي", "تامر", "هشام", "أيمن", "عادل", "صلاح",
    "زياد", "مروان", "بلال", "أنس", "سيف", "عمرو", "فارس", "آدم", "جمال",
    "نادر", "باسم", "أشرف", "مازن", "رضا", "عصام", "مجدي", "سعد", "منير",
]

FEMALE_GIVEN = [
    "فاطمة", "مريم", "نور", "سارة", "ياسمين", "هبة", "دينا", "منى", "ريهام",
    "شيماء", "أسماء", "إيمان", "رنا", "سلمى", "جنى", "ملك", "حبيبة", "آية",
    "رقية", "زينب", "هدى", "أمل", "نادية", "سمر", "ندى", "إسراء", "بسمة",
    "مي", "رحمة", "فرح", "أميرة", "شروق", "علياء", "وفاء", "هنا",
]

FAMILY = [
    "عبد العزيز", "السيد", "عبد الحميد", "حسن", "إبراهيم", "منصور", "الشناوي",
    "الجندي", "فهمي", "رشدي", "زكي", "الديب", "شلبي", "غانم", "البنا",
    "الحداد", "العطار", "سليمان", "مرسي", "صادق", "الشربيني", "عوض", "بدوي",
    "خليل", "نصر", "رياض", "سعيد", "فؤاد", "لطفي", "مبارك", "الطوخي",
    "الفقي", "شعبان", "درويش", "قنديل", "الأشقر", "حجازي", "عبد النبي",
]


class EgyptianPersonProvider(BaseProvider):
    """Egyptian personal names, in Arabic script."""

    def eg_given_name(self, sex: str = "male") -> str:
        pool = FEMALE_GIVEN if sex == "female" else MALE_GIVEN
        return self.random_element(pool)

    def eg_family_name(self) -> str:
        return self.random_element(FAMILY)

    def eg_full_name(self, sex: str = "male", parts: int | None = None) -> str:
        """given + father + [grandfather] + family.

        The father's and grandfather's names are always male given names,
        regardless of the player's own sex, which is what the convention is.
        """
        if parts is None:
            parts = 3 if self.generator.random.random() < 0.6 else 4
        names = [self.eg_given_name(sex)]
        names += [self.random_element(MALE_GIVEN) for _ in range(parts - 2)]
        names.append(self.eg_family_name())
        return " ".join(names)


def register(faker) -> None:
    faker.add_provider(EgyptianPersonProvider)
