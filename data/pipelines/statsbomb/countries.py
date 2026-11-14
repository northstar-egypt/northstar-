"""StatsBomb's country names as ISO 3166-1 alpha-2 codes, the form `Player.nationality` and
`Organization.country` hold. Covers every name in the competitions loaded (decision 0008); a
name not here is reported by load.py and stored without a code.

England, Scotland, Wales and Northern Ireland play as separate national teams but share one
ISO country, GB. Kosovo uses XK, the code in common use while it has no ISO entry.
"""

from __future__ import annotations

import unicodedata

_CODES = {
    "Albania": "AL", "Algeria": "DZ", "Angola": "AO", "Argentina": "AR", "Armenia": "AM",
    "Australia": "AU", "Austria": "AT", "Azerbaijan": "AZ", "Belarus": "BY", "Belgium": "BE",
    "Benin": "BJ", "Bermuda": "BM", "Bosnia and Herzegovina": "BA", "Brazil": "BR", "Bulgaria": "BG",
    "Burkina Faso": "BF", "Burundi": "BI", "Cameroon": "CM", "Canada": "CA", "Cape Verde": "CV",
    "Central African Republic": "CF", "Chad": "TD", "Chile": "CL", "China": "CN", "Colombia": "CO",
    "Comoros": "KM", "Congo, (Kinshasa)": "CD", "Congo (Brazzaville)": "CG", "Costa Rica": "CR",
    "Croatia": "HR", "Curacao": "CW", "Czech Republic": "CZ", "Cote d'Ivoire": "CI", "Denmark": "DK",
    "Ecuador": "EC", "Egypt": "EG", "England": "GB", "Equatorial Guinea": "GQ", "Finland": "FI",
    "France": "FR", "French Guiana": "GF", "Gabon": "GA", "Gambia": "GM", "Georgia": "GE",
    "Germany": "DE", "Ghana": "GH", "Greece": "GR", "Guadeloupe": "GP", "Guinea": "GN",
    "Guinea-Bissau": "GW", "Haiti": "HT", "Hungary": "HU", "Iceland": "IS",
    "Iran, Islamic Republic of": "IR", "Iraq": "IQ", "Ireland": "IE", "Italy": "IT", "Jamaica": "JM",
    "Japan": "JP", "Kazakhstan": "KZ", "Kenya": "KE", "Korea (South)": "KR", "Kosovo": "XK",
    "Lao PDR": "LA", "Libya": "LY", "Liechtenstein": "LI", "Lithuania": "LT",
    "Macedonia, Republic of": "MK", "Madagascar": "MG", "Mali": "ML", "Martinique": "MQ",
    "Mauritania": "MR", "Mauritius": "MU", "Mexico": "MX", "Moldova": "MD", "Monaco": "MC",
    "Montenegro": "ME", "Morocco": "MA", "Mozambique": "MZ", "Namibia": "NA", "Netherlands": "NL",
    "New Caledonia": "NC", "New Zealand": "NZ", "Nigeria": "NG", "Northern Ireland": "GB",
    "Norway": "NO", "Panama": "PA", "Paraguay": "PY", "Peru": "PE", "Poland": "PL", "Portugal": "PT",
    "Qatar": "QA", "Romania": "RO", "Russia": "RU", "Saudi Arabia": "SA", "Scotland": "GB",
    "Senegal": "SN", "Serbia": "RS", "Sierra Leone": "SL", "Slovakia": "SK", "Slovenia": "SI",
    "South Africa": "ZA", "Spain": "ES", "Sweden": "SE", "Switzerland": "CH",
    "Tanzania, United Republic of": "TZ", "Togo": "TG", "Tunisia": "TN", "Turkey": "TR",
    "Ukraine": "UA", "United States of America": "US", "Uruguay": "UY",
    "Venezuela (Bolivarian Republic)": "VE", "Wales": "GB", "Zambia": "ZM", "Zimbabwe": "ZW",
}


def _key(name: str) -> str:
    """Accents and odd spaces removed, case ignored: 'Côte d'Ivoire' and 'Cote d'Ivoire' agree."""
    # NFKD also turns a non-breaking space, which some StatsBomb names contain, into a space.
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return " ".join(plain.split()).casefold()


_BY_KEY = {_key(name): code for name, code in _CODES.items()}


def iso_code(name: str | None) -> str | None:
    """The ISO alpha-2 code for a StatsBomb country name, or None if it is not known."""
    return _BY_KEY.get(_key(name)) if name else None
