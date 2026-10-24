"""Egypt's 27 governorates: where a club or academy is, for coverage by governorate.

The federation's question is "where is the platform missing talent?", and players per million
people by governorate answers it: a governorate with no tracked players is a gap, whatever
the national total says. `Organization.region` holds one of these codes.

Codes are ISO 3166-2:EG, the standard identifier, so a governorate is never spelled two ways.

Population: the "Population (Nov. 2023 estimate)" column of the table in Wikipedia's
"Governorates of Egypt" article, read 2026-10-24 (total 106,668,704). The table cites CAPMAS
publications (Egypt in Figures 2015 and 2019) that do not obviously contain a 2023 figure, so
treat these as estimates to compare governorates with each other, not as census counts. They
are public aggregate statistics, not data about any person. Replace them with CAPMAS's own
figures when someone has them.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Governorate:
    code: str
    name: str
    name_ar: str
    population: int


GOVERNORATES: dict[str, Governorate] = {
    g.code: g
    for g in [
        Governorate("EG-ALX", "Alexandria", "الإسكندرية", 5_703_824),
        Governorate("EG-ASN", "Aswan", "أسوان", 1_698_201),
        Governorate("EG-AST", "Asyut", "أسيوط", 5_071_485),
        Governorate("EG-BH", "Beheira", "البحيرة", 6_940_234),
        Governorate("EG-BNS", "Beni Suef", "بني سويف", 3_618_395),
        Governorate("EG-C", "Cairo", "القاهرة", 10_456_284),
        Governorate("EG-DK", "Dakahlia", "الدقهلية", 7_058_212),
        Governorate("EG-DT", "Damietta", "دمياط", 2_023_380),
        Governorate("EG-FYM", "Faiyum", "الفيوم", 4_141_222),
        Governorate("EG-GH", "Gharbia", "الغربية", 5_483_000),
        Governorate("EG-GZ", "Giza", "الجيزة", 9_534_283),
        Governorate("EG-IS", "Ismailia", "الإسماعيلية", 1_482_999),
        Governorate("EG-KFS", "Kafr El Sheikh", "كفر الشيخ", 3_731_540),
        Governorate("EG-LX", "Luxor", "الأقصر", 1_429_385),
        Governorate("EG-MT", "Matrouh", "مطروح", 580_304),
        Governorate("EG-MN", "Minya", "المنيا", 6_332_918),
        Governorate("EG-MNF", "Monufia", "المنوفية", 4_743_341),
        Governorate("EG-WAD", "New Valley", "الوادي الجديد", 324_600),
        Governorate("EG-SIN", "North Sinai", "شمال سيناء", 544_494),
        Governorate("EG-PTS", "Port Said", "بورسعيد", 835_193),
        Governorate("EG-KB", "Qalyubia", "القليوبية", 6_137_896),
        Governorate("EG-KN", "Qena", "قنا", 3_651_215),
        Governorate("EG-BA", "Red Sea", "البحر الأحمر", 409_394),
        Governorate("EG-SHR", "Sharqia", "الشرقية", 8_032_683),
        Governorate("EG-SHG", "Sohag", "سوهاج", 5_714_903),
        Governorate("EG-JS", "South Sinai", "جنوب سيناء", 145_934),
        Governorate("EG-SUZ", "Suez", "السويس", 843_385),
    ]
}


def name_of(code: str | None) -> str | None:
    governorate = GOVERNORATES.get(code or "")
    return governorate.name if governorate else None
