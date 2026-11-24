"""Normalize free-text job fields into a stable dedupe key."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone

from jobdir.models import JobObservation

LEGAL_SUFFIXES = {
    "inc",
    "incorporated",
    "llc",
    "ltd",
    "limited",
    "corp",
    "corporation",
    "gmbh",
    "plc",
    "sa",
    "ag",
    "bv",
    "co",
    "company",
    "lp",
    "llp",
}

# ISO 3166-1 alpha-2 and common aliases -> canonical English name.
COUNTRIES: dict[str, str] = {
    "us": "United States",
    "usa": "United States",
    "u s": "United States",
    "u s a": "United States",
    "united states": "United States",
    "united states of america": "United States",
    "gb": "United Kingdom",
    "uk": "United Kingdom",
    "u k": "United Kingdom",
    "united kingdom": "United Kingdom",
    "great britain": "United Kingdom",
    "england": "United Kingdom",
    "scotland": "United Kingdom",
    "wales": "United Kingdom",
    "ca": "Canada",
    "canada": "Canada",
    "au": "Australia",
    "australia": "Australia",
    "nz": "New Zealand",
    "new zealand": "New Zealand",
    "ie": "Ireland",
    "ireland": "Ireland",
    "de": "Germany",
    "germany": "Germany",
    "deutschland": "Germany",
    "fr": "France",
    "france": "France",
    "es": "Spain",
    "spain": "Spain",
    "it": "Italy",
    "italy": "Italy",
    "nl": "Netherlands",
    "netherlands": "Netherlands",
    "the netherlands": "Netherlands",
    "holland": "Netherlands",
    "be": "Belgium",
    "belgium": "Belgium",
    "ch": "Switzerland",
    "switzerland": "Switzerland",
    "at": "Austria",
    "austria": "Austria",
    "se": "Sweden",
    "sweden": "Sweden",
    "no": "Norway",
    "norway": "Norway",
    "dk": "Denmark",
    "denmark": "Denmark",
    "fi": "Finland",
    "finland": "Finland",
    "pl": "Poland",
    "poland": "Poland",
    "pt": "Portugal",
    "portugal": "Portugal",
    "cz": "Czechia",
    "czechia": "Czechia",
    "czech republic": "Czechia",
    "ro": "Romania",
    "romania": "Romania",
    "hu": "Hungary",
    "hungary": "Hungary",
    "gr": "Greece",
    "greece": "Greece",
    "ee": "Estonia",
    "estonia": "Estonia",
    "lv": "Latvia",
    "latvia": "Latvia",
    "lt": "Lithuania",
    "lithuania": "Lithuania",
    "sk": "Slovakia",
    "slovakia": "Slovakia",
    "si": "Slovenia",
    "slovenia": "Slovenia",
    "hr": "Croatia",
    "croatia": "Croatia",
    "bg": "Bulgaria",
    "bulgaria": "Bulgaria",
    "rs": "Serbia",
    "serbia": "Serbia",
    "ua": "Ukraine",
    "ukraine": "Ukraine",
    "tr": "Turkey",
    "turkey": "Turkey",
    "turkiye": "Turkey",
    "il": "Israel",
    "israel": "Israel",
    "ae": "United Arab Emirates",
    "uae": "United Arab Emirates",
    "united arab emirates": "United Arab Emirates",
    "sa": "Saudi Arabia",
    "saudi arabia": "Saudi Arabia",
    "qa": "Qatar",
    "qatar": "Qatar",
    "sg": "Singapore",
    "singapore": "Singapore",
    "hk": "Hong Kong",
    "hong kong": "Hong Kong",
    "jp": "Japan",
    "japan": "Japan",
    "kr": "South Korea",
    "south korea": "South Korea",
    "korea": "South Korea",
    "republic of korea": "South Korea",
    "cn": "China",
    "china": "China",
    "in": "India",
    "india": "India",
    "id": "Indonesia",
    "indonesia": "Indonesia",
    "my": "Malaysia",
    "malaysia": "Malaysia",
    "th": "Thailand",
    "thailand": "Thailand",
    "vn": "Vietnam",
    "vietnam": "Vietnam",
    "ph": "Philippines",
    "philippines": "Philippines",
    "tw": "Taiwan",
    "taiwan": "Taiwan",
    "br": "Brazil",
    "brazil": "Brazil",
    "mx": "Mexico",
    "mexico": "Mexico",
    "ar": "Argentina",
    "argentina": "Argentina",
    "cl": "Chile",
    "chile": "Chile",
    "co": "Colombia",
    "colombia": "Colombia",
    "pe": "Peru",
    "peru": "Peru",
    "za": "South Africa",
    "south africa": "South Africa",
    "ng": "Nigeria",
    "nigeria": "Nigeria",
    "ke": "Kenya",
    "kenya": "Kenya",
    "eg": "Egypt",
    "egypt": "Egypt",
    "lu": "Luxembourg",
    "luxembourg": "Luxembourg",
    "is": "Iceland",
    "iceland": "Iceland",
    "mt": "Malta",
    "malta": "Malta",
    "cy": "Cyprus",
    "cyprus": "Cyprus",
    "ro": "Romania",
}

US_STATES = {
    "al": "Alabama",
    "ak": "Alaska",
    "az": "Arizona",
    "ar": "Arkansas",
    "ca": "California",
    "co": "Colorado",
    "ct": "Connecticut",
    "dc": "District of Columbia",
    "de": "Delaware",
    "fl": "Florida",
    "ga": "Georgia",
    "hi": "Hawaii",
    "ia": "Iowa",
    "id": "Idaho",
    "il": "Illinois",
    "in": "Indiana",
    "ks": "Kansas",
    "ky": "Kentucky",
    "la": "Louisiana",
    "ma": "Massachusetts",
    "md": "Maryland",
    "me": "Maine",
    "mi": "Michigan",
    "mn": "Minnesota",
    "mo": "Missouri",
    "ms": "Mississippi",
    "mt": "Montana",
    "nc": "North Carolina",
    "nd": "North Dakota",
    "ne": "Nebraska",
    "nh": "New Hampshire",
    "nj": "New Jersey",
    "nm": "New Mexico",
    "nv": "Nevada",
    "ny": "New York",
    "oh": "Ohio",
    "ok": "Oklahoma",
    "or": "Oregon",
    "pa": "Pennsylvania",
    "ri": "Rhode Island",
    "sc": "South Carolina",
    "sd": "South Dakota",
    "tn": "Tennessee",
    "tx": "Texas",
    "ut": "Utah",
    "va": "Virginia",
    "vt": "Vermont",
    "wa": "Washington",
    "wi": "Wisconsin",
    "wv": "West Virginia",
    "wy": "Wyoming",
}
US_STATE_NAMES = {v.lower(): k for k, v in US_STATES.items()}

CA_PROVINCES = {
    "ab": "Alberta",
    "bc": "British Columbia",
    "mb": "Manitoba",
    "nb": "New Brunswick",
    "nl": "Newfoundland and Labrador",
    "ns": "Nova Scotia",
    "nt": "Northwest Territories",
    "nu": "Nunavut",
    "on": "Ontario",
    "pe": "Prince Edward Island",
    "qc": "Quebec",
    "sk": "Saskatchewan",
    "yt": "Yukon",
}

PAY_RE = re.compile(
    r"(?ix)"
    r"(?P<cur1>usd|eur|gbp|cad|aud|chf|sgd|inr|jpy|\$|€|£)?\s*"
    r"(?P<a>\$|€|£)?\s*(?P<min>\d{1,3}(?:,\d{3})+|\d{4,7}(?:\.\d+)?)"
    r"\s*(?:k)?\s*(?:-|–|—|\bto\b)\s*"
    r"(?P<cur2>usd|eur|gbp|cad|aud|chf|sgd|\$|€|£)?\s*"
    r"(?P<b>\$|€|£)?\s*(?P<max>\d{1,3}(?:,\d{3})+|\d{4,7}(?:\.\d+)?)"
    r"\s*(?P<k>k)?"
)

CURRENCY_SYMBOL = {"$": "USD", "€": "EUR", "£": "GBP"}


def fold(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def norm_company(value: str | None) -> str:
    parts = fold(value).split()
    while parts and parts[-1] in LEGAL_SUFFIXES:
        parts.pop()
    return " ".join(parts)


def norm_title(value: str | None) -> str:
    text = fold(value)
    text = re.sub(r"\b(m f d|m w d|f m d|all genders)\b", "", text)
    return " ".join(text.split())


def canonical_country(value: str | None) -> str:
    key = fold(value)
    if not key:
        return ""
    if key in COUNTRIES:
        return COUNTRIES[key]
    if len(key) == 2 and key.isalpha():
        return COUNTRIES.get(key, "")
    return " ".join(part.capitalize() for part in key.split())


def _money(raw: str) -> float:
    return float(raw.replace(",", ""))


def parse_pay_text(text: str | None) -> tuple[float | None, float | None, str, str]:
    """Pull a single explicit range from a short compensation blurb."""
    if not text:
        return None, None, "", ""
    sample = " ".join(text.split())
    if len(sample) > 500:
        sample = sample[:500]
    match = PAY_RE.search(sample)
    if not match:
        return None, None, "", ""
    low = _money(match.group("min"))
    high = _money(match.group("max"))
    if match.group("k"):
        low *= 1000
        high *= 1000
    elif low < 1000 and high < 1000 and re.search(r"(?i)\b\d+\s*k\b", match.group(0)):
        low *= 1000
        high *= 1000
    cur_token = (match.group("cur1") or match.group("cur2") or match.group("a") or match.group("b") or "").lower()
    currency = CURRENCY_SYMBOL.get(cur_token, cur_token.upper())
    if not currency and (match.group("a") or match.group("b")):
        currency = "USD"
    # Reject bare ranges that are not obviously pay.
    if not currency and low < 15000:
        return None, None, "", ""
    if low > high:
        low, high = high, low
    if high > 5_000_000 or low <= 0:
        return None, None, "", ""
    period = "year"
    window = sample[max(0, match.start() - 40) : match.end() + 40].lower()
    if any(word in window for word in ("hour", "hourly", "/hr", "per hour")) or (currency and high < 500):
        period = "hour"
    elif any(word in window for word in ("month", "monthly", "/mo")):
        period = "month"
    elif "week" in window:
        period = "week"
    return low, high, currency or "USD", period


def parse_posted(value, *, today: date | None = None) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)):
        stamp = float(value)
        if stamp > 10_000_000_000:
            stamp /= 1000
        return datetime.fromtimestamp(stamp, tz=timezone.utc).date().isoformat()
    text = str(value).strip()
    iso = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if iso:
        return f"{iso.group(1)}-{iso.group(2)}-{iso.group(3)}"
    today = today or datetime.now(timezone.utc).date()
    lowered = text.lower()
    if "today" in lowered:
        return today.isoformat()
    if "yesterday" in lowered:
        return (today - timedelta(days=1)).isoformat()
    days = re.search(r"(\d+)\s*\+?\s*days?\s+ago", lowered)
    if days:
        return (today - timedelta(days=int(days.group(1)))).isoformat()
    return ""


# 2-letter tokens that are US states in "City, ST" postings even when the
# same letters are also an ISO country (CA, IL, IN, DE, CO, ...).
_STATE_FIRST = set(US_STATES) - {"de"}
_GERMAN_CITIES = {
    "berlin",
    "munich",
    "munchen",
    "frankfurt",
    "hamburg",
    "cologne",
    "koln",
    "stuttgart",
    "dusseldorf",
    "düsseldorf",
    "leipzig",
    "dortmund",
    "essen",
    "bremen",
    "dresden",
    "hanover",
    "hannover",
    "nuremberg",
    "nurnberg",
}


def _peel_country_and_region(parts: list[str], country: str, region: str) -> tuple[list[str], str, str]:
    cleaned = list(parts)
    if not cleaned:
        return cleaned, country, region
    last = cleaned[-1]
    last_fold = fold(last)
    prev = fold(cleaned[-2]) if len(cleaned) >= 2 else ""
    if len(last) == 2 and last.lower() == "de" and prev in _GERMAN_CITIES:
        return cleaned[:-1], country or "Germany", region
    if len(last) == 2 and last.lower() in US_STATES and country in {"", "United States"} and not (
        last.lower() == "de" and prev in _GERMAN_CITIES
    ):
        # Prefer US state for "City, ST", including codes that collide with countries.
        if last.lower() in _STATE_FIRST or last.lower() in US_STATES:
            return cleaned[:-1], country or "United States", region or US_STATES[last.lower()]
    if last_fold in US_STATE_NAMES and country in {"", "United States"} and len(cleaned) >= 2:
        return cleaned[:-1], country or "United States", region or last
    if last.lower() in COUNTRIES or last_fold in COUNTRIES:
        return cleaned[:-1], country or canonical_country(last), region
    if last_fold in {fold(v) for v in CA_PROVINCES.values()} or (
        len(last) == 2 and last.lower() in CA_PROVINCES and country in {"", "Canada"}
    ):
        name = CA_PROVINCES.get(last.lower(), last)
        return cleaned[:-1], country or "Canada", region or name
    return cleaned, country, region


def _clean_place(value: str) -> str:
    text = re.sub(r"(?i)\b(remote|hybrid|on-?site|onsite|hq|headquarters|office)\b", " ", value or "")
    text = text.replace("(", " ").replace(")", " ")
    text = re.sub(r"\s+", " ", text).strip(" ,-/")
    return text


def interpret_location(
    location_raw: str = "",
    *,
    city: str = "",
    region: str = "",
    country: str = "",
    remote: bool | None = None,
    workplace: str = "",
) -> tuple[str, str, str, bool | None, str]:
    """Return city, region, country, remote flag, workplace."""
    city = (city or "").strip(" ,")
    region = (region or "").strip(" ,")
    country = canonical_country(country)
    workplace = (workplace or "").strip().lower()
    raw = " ".join((location_raw or "").split())

    if workplace in {"remote", "hybrid", "onsite"}:
        pass
    elif remote is True and not city and not raw:
        workplace = "remote"
    else:
        blob = f"{raw} {city}".lower()
        has_remote = bool(re.search(r"\bremote\b", blob))
        has_hybrid = "hybrid" in blob
        place_only = _clean_place(raw)
        place_fold = fold(place_only)
        country_only = place_fold in COUNTRIES or place_fold in {"us", "usa", "uk"}
        if has_hybrid:
            workplace = "hybrid"
        elif has_remote and (not place_only or country_only):
            workplace = "remote"
        elif has_remote:
            # "New York or Remote" still names a city, so it is not remote-only.
            workplace = "hybrid"
        elif re.search(r"\bon-?site\b", blob):
            workplace = "onsite"

    # Workday style: "US, CA, Santa Clara"
    wd = re.match(r"^([A-Za-z]{2}),\s*([A-Za-z]{2}),\s*(.+)$", raw)
    if wd and not city:
        country = country or canonical_country(wd.group(1))
        region_code = wd.group(2).lower()
        region = region or US_STATES.get(region_code, wd.group(2))
        city = wd.group(3).strip()
        if region_code in US_STATES and not country:
            country = "United States"

    if not city and raw and "locations" not in raw.lower():
        parts = [p.strip() for p in re.split(r",| - | – | — |\|", raw) if p.strip()]
        cleaned = []
        for part in parts:
            if re.search(r"(?i)\b(remote|hybrid|on-?site|multiple|locations)\b", part) and not re.search(r"[A-Za-z]{4}", _clean_place(part)):
                continue
            piece = _clean_place(part)
            if piece:
                cleaned.append(piece)
        if cleaned:
            while cleaned:
                nxt, country, region = _peel_country_and_region(cleaned, country, region)
                if len(nxt) == len(cleaned):
                    break
                cleaned = nxt
            if cleaned and not city:
                city = cleaned[0]

    city = _clean_place(city)
    if re.fullmatch(r"(?i)\d+\s+locations?", raw or city or ""):
        city = ""
    if city.lower() in {"remote", "hybrid", "anywhere", "global"}:
        city = ""

    if not country and region:
        if fold(region) in US_STATE_NAMES or (len(region) == 2 and region.lower() in US_STATES):
            country = "United States"
            if len(region) == 2 and region.lower() in US_STATES:
                region = US_STATES[region.lower()]
        elif len(region) == 2 and region.lower() in CA_PROVINCES:
            country = "Canada"
            region = CA_PROVINCES[region.lower()]

    if workplace == "remote":
        remote_flag: bool | None = True
    elif workplace == "hybrid":
        remote_flag = False
    elif workplace == "onsite":
        remote_flag = False
    elif remote is not None:
        remote_flag = remote
        workplace = workplace or ("remote" if remote else "")
    else:
        remote_flag = None

    return city, region, country, remote_flag, workplace


def location_key(city: str, region: str, country: str, remote: bool | None, workplace: str, location_raw: str) -> str:
    city_n = fold(city)
    country_n = fold(country)
    if (workplace == "remote" or remote is True) and not city_n:
        return f"remote|{country_n}"
    if city_n or country_n:
        return f"{city_n}|{country_n}"
    raw = fold(location_raw)
    return raw or "unspecified"


def job_id_for(company: str, title: str, loc_key: str) -> str:
    raw = f"{norm_company(company)}|{norm_title(title)}|{loc_key}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def finalize_observation(obs: JobObservation) -> tuple[JobObservation, str, str]:
    """Fill derived location fields. Returns observation, job id, location key."""
    city, region, country, remote, workplace = interpret_location(
        obs.location_raw,
        city=obs.city,
        region=obs.region,
        country=obs.country,
        remote=obs.remote,
        workplace=obs.workplace,
    )
    obs.city = city
    obs.region = region
    obs.country = country
    obs.remote = remote
    obs.workplace = workplace
    obs.company = " ".join((obs.company or "").split())
    obs.title = " ".join((obs.title or "").split())
    obs.pay_currency = (obs.pay_currency or "").upper()
    loc_key = location_key(city, region, country, remote, workplace, obs.location_raw)
    jid = job_id_for(obs.company, obs.title, loc_key)
    return obs, jid, loc_key


def observation_payload(obs: JobObservation) -> dict:
    return {
        "company": obs.company,
        "title": obs.title,
        "location_raw": obs.location_raw,
        "city": obs.city,
        "region": obs.region,
        "country": obs.country,
        "remote": obs.remote,
        "workplace": obs.workplace,
        "pay_min": obs.pay_min,
        "pay_max": obs.pay_max,
        "pay_currency": obs.pay_currency,
        "pay_period": obs.pay_period,
        "department": obs.department,
        "employment_type": obs.employment_type,
        "posted_at": obs.posted_at,
        "apply_url": obs.apply_url,
        "sector": obs.sector,
        "source_job_id": obs.source_job_id,
    }
