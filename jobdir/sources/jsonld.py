"""Extract schema.org JobPosting objects from HTML JSON-LD blocks."""

from __future__ import annotations

import json
from html.parser import HTMLParser

from jobdir.models import JobObservation
from jobdir.normalize import parse_posted


class _JsonLdParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._capture = False
        self._parts: list[str] = []
        self.blocks: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "script":
            return
        kind = ""
        for key, value in attrs:
            if key.lower() == "type":
                kind = (value or "").lower()
        if kind == "application/ld+json":
            self._capture = True
            self._parts = []

    def handle_endtag(self, tag):
        if tag.lower() == "script" and self._capture:
            self.blocks.append("".join(self._parts))
            self._capture = False

    def handle_data(self, data):
        if self._capture:
            self._parts.append(data)


def iter_job_postings(node):
    if isinstance(node, list):
        for item in node:
            yield from iter_job_postings(item)
        return
    if not isinstance(node, dict):
        return
    types = node.get("@type") or []
    if isinstance(types, str):
        types = [types]
    if any(str(item).lower().split("/")[-1] == "jobposting" for item in types):
        yield node
    graph = node.get("@graph")
    if graph:
        yield from iter_job_postings(graph)


def extract_jsonld_blocks(html: str) -> list:
    parser = _JsonLdParser()
    parser.feed(html)
    found = []
    for block in parser.blocks:
        text = block.strip()
        if not text:
            continue
        try:
            found.append(json.loads(text))
        except json.JSONDecodeError:
            continue
    return found


def _org_name(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        name = value.get("name") or value.get("legalName") or ""
        if isinstance(name, str):
            return name.strip()
    if isinstance(value, list) and value:
        return _org_name(value[0])
    return ""


def _address(job: dict) -> tuple[str, str, str, str]:
    location = job.get("jobLocation")
    if isinstance(location, list):
        location = location[0] if location else {}
    if not isinstance(location, dict):
        return "", "", "", ""
    address = location.get("address") or {}
    if isinstance(address, list):
        address = address[0] if address else {}
    if isinstance(address, str):
        return address, "", "", ""
    if not isinstance(address, dict):
        return "", "", "", ""
    country = address.get("addressCountry") or ""
    if isinstance(country, dict):
        country = country.get("name") or country.get("addressCountry") or ""
    return (
        "",
        address.get("addressLocality") or "",
        address.get("addressRegion") or "",
        country if isinstance(country, str) else "",
    )


def _salary(job: dict) -> tuple[float | None, float | None, str, str]:
    salary = job.get("baseSalary")
    if isinstance(salary, list):
        salary = salary[0] if salary else None
    if not isinstance(salary, dict):
        return None, None, "", ""
    currency = salary.get("currency") or ""
    value = salary.get("value") or {}
    if isinstance(value, list):
        value = value[0] if value else {}
    if not isinstance(value, dict):
        try:
            amount = float(value)
        except (TypeError, ValueError):
            return None, None, currency, ""
        return amount, amount, currency, "year"
    low = value.get("minValue", value.get("value"))
    high = value.get("maxValue", value.get("value"))
    try:
        low_n = float(low) if low not in (None, "") else None
    except (TypeError, ValueError):
        low_n = None
    try:
        high_n = float(high) if high not in (None, "") else None
    except (TypeError, ValueError):
        high_n = None
    unit = (value.get("unitText") or "").upper()
    period = {"HOUR": "hour", "MONTH": "month", "WEEK": "week", "DAY": "day", "YEAR": "year"}.get(unit, "year" if unit == "" else unit.lower())
    return low_n, high_n, currency, period


def jobposting_to_observation(job: dict, *, page_url: str, sector: str = "") -> JobObservation | None:
    title = job.get("title") or ""
    if isinstance(title, dict):
        title = title.get("name") or ""
    title = str(title).strip()
    company = _org_name(job.get("hiringOrganization"))
    if not title or not company:
        return None
    _raw, city, region, country = _address(job)
    location_type = str(job.get("jobLocationType") or "")
    remote = None
    workplace = ""
    if "telecommute" in location_type.lower() or location_type.lower() == "remote":
        remote = True
        workplace = "remote"
    identifier = job.get("identifier")
    source_id = ""
    if isinstance(identifier, dict):
        source_id = str(identifier.get("value") or "")
    elif isinstance(identifier, str):
        source_id = identifier
    url = job.get("url") or page_url
    if isinstance(url, list):
        url = url[0] if url else page_url
    if not source_id:
        source_id = str(url or page_url)
    pay_min, pay_max, currency, period = _salary(job)
    return JobObservation(
        source="commoncrawl",
        board_id="commoncrawl",
        source_job_id=source_id[:180],
        company=company,
        title=title,
        apply_url=str(url or page_url),
        location_raw=_raw or ", ".join(part for part in (city, region, country) if part),
        city=city if isinstance(city, str) else "",
        region=region if isinstance(region, str) else "",
        country=country if isinstance(country, str) else "",
        remote=remote,
        workplace=workplace,
        pay_min=pay_min,
        pay_max=pay_max,
        pay_currency=currency,
        pay_period=period,
        department=str(job.get("occupationalCategory") or job.get("industry") or "")[:120],
        employment_type=str(job.get("employmentType") or "")[:80],
        posted_at=parse_posted(job.get("datePosted")),
        sector=sector,
    )


def observations_from_html(html: str, page_url: str) -> list[JobObservation]:
    found = []
    for block in extract_jsonld_blocks(html):
        for job in iter_job_postings(block):
            obs = jobposting_to_observation(job, page_url=page_url)
            if obs:
                found.append(obs)
    return found
