"""Find ATS board ids from a known-company catalog and from career URLs.

Common Crawl URL discovery is optional and resumable. The vendored catalog is
the public-domain board directory checked into data/discovery/.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Iterable
from urllib.parse import urlparse

from jobdir.models import Board

_GH = re.compile(r"(?:boards|job-boards)\.greenhouse\.io/(?:v1/boards/)?([A-Za-z0-9_-]+)", re.I)
_GH_API = re.compile(r"boards-api\.greenhouse\.io/v1/boards/([A-Za-z0-9_-]+)", re.I)
_LEVER = re.compile(r"jobs(?:\.eu)?\.lever\.co/([A-Za-z0-9_-]+)", re.I)
_LEVER_API = re.compile(r"api(?:\.eu)?\.lever\.co/v0/postings/([A-Za-z0-9_-]+)", re.I)
_ASHBY = re.compile(r"(?:jobs\.ashbyhq\.com|api\.ashbyhq\.com/posting-api/job-board)/([A-Za-z0-9_-]+)", re.I)
_WK = re.compile(r"apply\.workable\.com/(?!api(?:/|$)|j/|view/|embed/)([A-Za-z0-9_-]+)", re.I)
_SR = re.compile(r"(?:jobs\.smartrecruiters\.com|api\.smartrecruiters\.com/v1/companies)/([A-Za-z0-9_-]+)", re.I)
_RC = re.compile(r"https?://([A-Za-z0-9_-]+)\.recruitee\.com", re.I)
_WD = re.compile(
    r"https?://(?P<host>[a-z0-9.-]+\.myworkdayjobs\.com)(?:/[a-z]{2}-[A-Za-z]{2})?/(?P<site>[A-Za-z0-9_-]+)",
    re.I,
)
_SKIP_TOKENS = {"embed", "api", "j", "jobs", "job", "www", "static", "assets"}


def parse_board_url(url: str) -> Board | None:
    if not url:
        return None
    for pattern, source in (
        (_GH_API, "greenhouse"),
        (_GH, "greenhouse"),
        (_LEVER_API, "lever"),
        (_LEVER, "lever"),
        (_ASHBY, "ashby"),
        (_WK, "workable"),
        (_SR, "smartrecruiters"),
    ):
        match = pattern.search(url)
        if match:
            token = match.group(1)
            if token.lower() in _SKIP_TOKENS:
                return None
            api_base = ""
            if source == "lever" and ("api.eu.lever.co" in url or "jobs.eu.lever.co" in url):
                api_base = "https://api.eu.lever.co"
            return Board(company=token, source=source, board_id=token, careers_url=url, api_base=api_base)
    match = _RC.search(url)
    if match:
        token = match.group(1)
        if token.lower() in _SKIP_TOKENS:
            return None
        return Board(company=token, source="recruitee", board_id=token, careers_url=url)
    cxs = re.search(r"https://([^/]+)/wday/cxs/([^/]+)/([^/]+)/jobs", url, re.I)
    if cxs:
        return Board(
            company=cxs.group(2),
            source="workday",
            board_id=cxs.group(2),
            careers_url=url,
            workday_host=cxs.group(1),
            workday_tenant=cxs.group(2),
            workday_site=cxs.group(3),
        )
    match = _WD.search(url)
    if match:
        host = match.group("host").lower()
        site = match.group("site")
        if site.lower() in _SKIP_TOKENS:
            return None
        tenant = host.split(".")[0]
        return Board(
            company=tenant,
            source="workday",
            board_id=tenant,
            careers_url=url,
            workday_host=host,
            workday_tenant=tenant,
            workday_site=site,
        )
    return None


def load_catalog(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def catalog_to_boards(rows: Iterable[dict], sources: set[str] | None = None) -> list[Board]:
    boards = []
    for row in rows:
        source = (row.get("platform") or "").strip().lower()
        if sources and source not in sources:
            continue
        if source not in {"greenhouse", "ashby", "lever", "workable", "recruitee", "workday"}:
            continue
        try:
            roles = int(row.get("open_roles") or 0)
        except ValueError:
            roles = 0
        if roles <= 0:
            continue
        parsed = parse_board_url(row.get("api_url") or row.get("board_url") or "")
        if parsed is None or parsed.source != source:
            parsed = parse_board_url(row.get("board_url") or "")
        if parsed is None:
            continue
        company = (row.get("company") or parsed.company or parsed.board_id).strip()
        parsed.company = company or parsed.board_id
        parsed.careers_url = row.get("board_url") or parsed.careers_url
        if source == "lever":
            api = row.get("api_url") or ""
            host = urlparse(api).scheme + "://" + urlparse(api).netloc if urlparse(api).netloc else ""
            parsed.api_base = host
        if source == "workday":
            api = row.get("api_url") or ""
            wd = re.search(r"https://([^/]+)/wday/cxs/([^/]+)/([^/]+)/jobs", api)
            if wd:
                parsed.workday_host = wd.group(1)
                parsed.workday_tenant = wd.group(2)
                parsed.workday_site = wd.group(3)
                parsed.board_id = wd.group(2)
        boards.append(parsed)
    return boards


def missing_boards(catalog: list[Board], existing: list[Board]) -> list[Board]:
    have = {(board.source, board.board_id) for board in existing}
    found = []
    seen = set()
    for board in catalog:
        key = (board.source, board.board_id)
        if key in have or key in seen:
            continue
        seen.add(key)
        found.append(board)
    return found
