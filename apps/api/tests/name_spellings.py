"""Latin spellings of every name part the synthetic generator uses, for scoring name search.

Written before the matcher in app/names.py, from the spellings that actually turn up in
Egyptian passports, club registrations and football coverage (Mohamed Salah, Ahmed Hegazi,
Mahmoud Trezeguet...), not from what the matcher happens to handle. Several per name, because
there is no single standard: the same player is Mohamed on his passport, Mohammed in an
English report and Muhammad in a scout's notes.

The names are split in two by `half()`. The matcher's rules were adjusted only while looking
at failures in the "tune" half; the "held out" half is what gets reported. Same discipline as
the detector thresholds in ml/README.md.

Synthetic reference data, not player records: these are common given and family names.
"""

from __future__ import annotations

import hashlib

SPELLINGS: dict[str, list[str]] = {
    # Male given names
    "محمد": ["Mohamed", "Mohammed", "Muhammad", "Mohamad", "Mohammad"],
    "أحمد": ["Ahmed", "Ahmad"],
    "محمود": ["Mahmoud", "Mahmud", "Mahmood"],
    "مصطفى": ["Mostafa", "Mustafa", "Moustafa", "Mostapha"],
    "خالد": ["Khaled", "Khalid"],
    "عمر": ["Omar", "Umar"],
    "يوسف": ["Youssef", "Yousef", "Yusuf", "Youssif", "Yousif"],
    "كريم": ["Karim", "Kareem"],
    "إسلام": ["Islam", "Eslam"],
    "حسن": ["Hassan", "Hasan"],
    "حسين": ["Hussein", "Hossein", "Hussain", "Hosein"],
    "إبراهيم": ["Ibrahim", "Ebrahim"],
    "عبد الرحمن": ["Abdelrahman", "Abdel Rahman", "Abdulrahman", "Abd El-Rahman", "Abdalrahman"],
    "عبد الله": ["Abdallah", "Abdullah", "Abdalla"],
    "طارق": ["Tarek", "Tariq", "Tarik"],
    "شريف": ["Sherif", "Sharif", "Cherif"],
    "هيثم": ["Haitham", "Haytham", "Heitham"],
    "ياسر": ["Yasser", "Yasir", "Yaser"],
    "سامح": ["Sameh"],
    "وليد": ["Walid", "Waleed"],
    "رامي": ["Ramy", "Rami"],
    "تامر": ["Tamer"],
    "هشام": ["Hesham", "Hisham"],
    "أيمن": ["Ayman", "Aiman"],
    "عادل": ["Adel", "Adil"],
    "صلاح": ["Salah"],
    "زياد": ["Ziad", "Ziyad"],
    "مروان": ["Marwan"],
    "بلال": ["Belal", "Bilal"],
    "أنس": ["Anas"],
    "سيف": ["Seif", "Saif", "Sayf"],
    "عمرو": ["Amr", "Amro", "Amrou"],
    "فارس": ["Fares", "Faris"],
    "آدم": ["Adam"],
    "جمال": ["Gamal", "Jamal"],
    "نادر": ["Nader", "Nadir"],
    "باسم": ["Bassem", "Basem", "Basim"],
    "أشرف": ["Ashraf"],
    "مازن": ["Mazen"],
    "رضا": ["Reda", "Ridha", "Rida"],
    "عصام": ["Essam", "Issam", "Esam"],
    "مجدي": ["Magdy", "Magdi", "Majdi"],
    "سعد": ["Saad", "Sa'ad"],
    "منير": ["Mounir", "Monir", "Munir"],
    # Female given names
    "فاطمة": ["Fatma", "Fatima", "Fatmah"],
    "مريم": ["Mariam", "Maryam", "Meriam"],
    "نور": ["Nour", "Noor", "Nur"],
    "سارة": ["Sara", "Sarah"],
    "ياسمين": ["Yasmin", "Yasmine", "Yasmeen"],
    "هبة": ["Heba", "Hiba"],
    "دينا": ["Dina"],
    "منى": ["Mona", "Muna"],
    "ريهام": ["Reham", "Riham"],
    "شيماء": ["Shaimaa", "Shaima", "Shimaa"],
    "أسماء": ["Asmaa", "Asma"],
    "إيمان": ["Eman", "Iman"],
    "رنا": ["Rana"],
    "سلمى": ["Salma"],
    "جنى": ["Gana", "Jana"],
    "ملك": ["Malak"],
    "حبيبة": ["Habiba", "Habibah"],
    "آية": ["Aya", "Ayah"],
    "رقية": ["Roqaya", "Ruqayya", "Rokaya"],
    "زينب": ["Zeinab", "Zainab", "Zaynab"],
    "هدى": ["Hoda", "Huda"],
    "أمل": ["Amal"],
    "نادية": ["Nadia", "Nadya"],
    "سمر": ["Samar"],
    "ندى": ["Nada"],
    "إسراء": ["Esraa", "Israa", "Esra"],
    "بسمة": ["Basma"],
    "مي": ["Mai", "May", "Mayy"],
    "رحمة": ["Rahma", "Rahmah"],
    "فرح": ["Farah"],
    "أميرة": ["Amira", "Ameera"],
    "شروق": ["Shorouk", "Shrouk", "Shurouq"],
    "علياء": ["Alyaa", "Aliaa", "Alia"],
    "وفاء": ["Wafaa", "Wafa"],
    "هنا": ["Hana", "Hanaa"],
    # Family names (حسن and إبراهيم appear above)
    "عبد العزيز": ["Abdelaziz", "Abdel Aziz", "Abdulaziz", "Abd El-Aziz"],
    "السيد": ["El-Sayed", "Elsayed", "El Sayed", "Al-Sayed", "Sayed"],
    "عبد الحميد": ["Abdelhamid", "Abdel Hamid", "Abdulhamid", "Abd El-Hamid"],
    "منصور": ["Mansour", "Mansur"],
    "الشناوي": ["El-Shenawy", "Elshenawy", "El Shennawy", "Shenawy"],
    "الجندي": ["El-Gendy", "Elgendy", "El Gindy", "Gendy"],
    "فهمي": ["Fahmy", "Fahmi"],
    "رشدي": ["Roshdy", "Rushdi", "Rushdy"],
    "زكي": ["Zaki", "Zaky"],
    "الديب": ["El-Deeb", "Eldib", "El Dib"],
    "شلبي": ["Shalaby", "Shalabi", "Chalaby"],
    "غانم": ["Ghanem", "Ghanim"],
    "البنا": ["El-Banna", "Elbanna", "Al-Banna"],
    "الحداد": ["El-Haddad", "Elhaddad", "Haddad"],
    "العطار": ["El-Attar", "Elattar", "Al-Attar"],
    "سليمان": ["Soliman", "Suleiman", "Sulaiman", "Sleiman"],
    "مرسي": ["Morsy", "Morsi", "Mursi"],
    "صادق": ["Sadek", "Sadiq", "Sadik"],
    "الشربيني": ["El-Sherbiny", "Elsherbini", "El Sherbeeny"],
    "عوض": ["Awad"],
    "بدوي": ["Badawy", "Badawi"],
    "خليل": ["Khalil"],
    "نصر": ["Nasr"],
    "رياض": ["Riad", "Riyad", "Reyad"],
    "سعيد": ["Saeed", "Said", "Saied"],
    "فؤاد": ["Fouad", "Fuad"],
    "لطفي": ["Lotfy", "Lutfi", "Lotfi"],
    "مبارك": ["Mubarak", "Mobarak"],
    "الطوخي": ["El-Toukhy", "Eltokhy", "El Tokhi"],
    "الفقي": ["El-Feky", "Elfeki", "El Fiqi"],
    "شعبان": ["Shaaban", "Shaban", "Chaabane"],
    "درويش": ["Darwish", "Darwich"],
    "قنديل": ["Kandil", "Qandil", "Kandeel"],
    "الأشقر": ["El-Ashkar", "Elashkar", "Al-Ashqar"],
    "حجازي": ["Hegazy", "Hegazi", "Higazi", "Hijazi"],
    "عبد النبي": ["Abdelnaby", "Abdel Nabi", "Abdulnabi"],
}


def half(arabic: str) -> str:
    """'tune' or 'held out', fixed by a hash of the name so it never depends on list order."""
    digest = hashlib.sha256(arabic.encode("utf-8")).digest()
    return "tune" if digest[0] % 2 == 0 else "held out"
