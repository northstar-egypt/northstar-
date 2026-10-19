"""A fresh set of Latin spellings, for judging the double-vowel rule (board card "Name search
precision: treat Latin double vowels as long vowels").

Why a second set: the rule was spotted while looking at failures in the held-out half of
tests/name_spellings.py, so that half can no longer judge it fairly. These spellings were
written on 2026-10-19, before the rule, and committed on their own before any change to
app/names.py, so the git history shows they could not have been fitted to it. They were not
run through the matcher while being written.

Every spelling here is one not already in name_spellings.py, for the same Arabic names (the
names the synthetic generator uses, so search precision can be measured on a generated
dataset). They come from the same sources as the first set: Egyptian passports and club
registrations, English-language coverage, and the French-style spellings common across North
Africa and in European club data (Youssouf, Houda, Chaimaa), which is where Latin double
vowels that are short vowels in Arabic mostly come from. Names with no further realistic
spelling are left out rather than padded.

Synthetic reference data, not player records: these are common given and family names.
"""

from __future__ import annotations

FRESH: dict[str, list[str]] = {
    # Male given names
    "محمد": ["Muhammed", "Mouhamed"],
    "محمود": ["Mahmod"],
    "مصطفى": ["Moustapha", "Mustapha"],
    "عمر": ["Omer", "Oumar"],
    "يوسف": ["Youcef", "Youssouf", "Yousuf"],
    "كريم": ["Kerim"],
    "حسن": ["Hassen"],
    "حسين": ["Hussien", "Houssein", "Husein"],
    "إبراهيم": ["Ibraheem", "Ibrahem"],
    "عبد الرحمن": ["Abderrahmane", "Abdurrahman", "Abdel-Rahman"],
    "عبد الله": ["Abdellah", "Abdulla"],
    "طارق": ["Tareq"],
    "شريف": ["Shereef"],
    "هيثم": ["Haithem"],
    "ياسر": ["Yassir"],
    "سامح": ["Samih"],
    "وليد": ["Oualid", "Walied"],
    "تامر": ["Tamir"],
    "هشام": ["Hicham"],
    "أيمن": ["Aymen"],
    "عادل": ["Aadel"],
    "صلاح": ["Salaah"],
    "زياد": ["Zeyad"],
    "مروان": ["Merwan"],
    "بلال": ["Bellal"],
    "أنس": ["Anass"],
    "سيف": ["Seyf"],
    "عمرو": ["Amru"],
    "فارس": ["Farris"],
    "جمال": ["Djamel", "Gamaal"],
    "باسم": ["Bassim"],
    "أشرف": ["Achraf"],
    "مازن": ["Mazin"],
    "رضا": ["Redha"],
    "عصام": ["Issame"],
    "مجدي": ["Mejdi"],
    "منير": ["Moneer"],
    # Female given names
    "فاطمة": ["Fatema", "Fatemah"],
    "مريم": ["Meriem", "Mariem"],
    "ياسمين": ["Yassmine"],
    "هبة": ["Hebah"],
    "منى": ["Mouna"],
    "ريهام": ["Reeham"],
    "شيماء": ["Chaimaa", "Shaymaa"],
    "أسماء": ["Asmae"],
    "إيمان": ["Imane"],
    "سلمى": ["Selma"],
    "حبيبة": ["Habeeba"],
    "رقية": ["Rokaia", "Roukaya"],
    "زينب": ["Zeynab"],
    "هدى": ["Houda"],
    "أمل": ["Amel"],
    "إسراء": ["Isra"],
    "شروق": ["Chorouk", "Shorouq"],
    "علياء": ["Aliya"],
    "وفاء": ["Wafae"],
    # Family names
    "عبد العزيز": ["Abdul-Aziz"],
    "السيد": ["El-Saied", "Elsaid"],
    "عبد الحميد": ["Abdelhamed"],
    "منصور": ["Mansoor"],
    "الشناوي": ["El-Shinawy"],
    "الجندي": ["El-Guindy"],
    "فهمي": ["Fehmi"],
    "رشدي": ["Rochdi"],
    "الديب": ["Eldeeb"],
    "غانم": ["Ganem"],
    "سليمان": ["Slimane", "Soleiman"],
    "مرسي": ["Moursi"],
    "صادق": ["Sadeq"],
    "الشربيني": ["El-Sherbeny"],
    "بدوي": ["Badaoui"],
    "خليل": ["Khaleel"],
    "رياض": ["Riyadh"],
    "سعيد": ["Saeid"],
    "فؤاد": ["Foad"],
    "لطفي": ["Lutfy"],
    "مبارك": ["Moubarak"],
    "الطوخي": ["El-Tokhy"],
    "شعبان": ["Chaaban"],
    "درويش": ["Darweesh"],
    "قنديل": ["Qandeel"],
    "حجازي": ["Higazy"],
    "عبد النبي": ["Abdennabi"],
}
