"""USAJobs public search API. Optional: skipped cleanly when no key is configured."""

from __future__ import annotations

import os

from jobdir.http import Client, HttpError
from jobdir.models import Board, FetchResult, JobObservation
from jobdir.normalize import parse_posted

API = "https://data.usajobs.gov/api/search"


class USAJobsAdapter:
    name = "usajobs"
    kind = "live_board"

    def __init__(self, page_size: int = 500, max_pages: int = 20):
        self.page_size = page_size
        self.max_pages = max_pages

    def fetch(self, board: Board, client: Client) -> FetchResult:
        key = os.environ.get("USAJOBS_API_KEY", "").strip()
        agent = os.environ.get("USAJOBS_USER_AGENT", "").strip()
        if not key or not agent:
            return FetchResult(
                source=self.name,
                board_id=board.board_id or "usajobs",
                success=True,
                complete=False,
                kind=self.kind,
                skipped=True,
                error="USAJOBS_API_KEY or USAJOBS_USER_AGENT is unset; skipping USAJobs",
            )
        headers = {
            "Authorization-Key": key,
            "User-Agent": agent,
            "Host": "data.usajobs.gov",
            "Accept": "application/json",
        }
        observations = []
        try:
            first = client.get_json(
                f"{API}?ResultsPerPage={self.page_size}&Page=1",
                headers=headers,
                timeout=60,
            )
            search = first.get("SearchResult") or {}
            count = int(search.get("SearchResultCountAll") or 0)
            pages = min(self.max_pages, max(1, (count + self.page_size - 1) // self.page_size))
            observations.extend(self._page(board, search))
            for page in range(2, pages + 1):
                payload = client.get_json(
                    f"{API}?ResultsPerPage={self.page_size}&Page={page}",
                    headers=headers,
                    timeout=60,
                )
                observations.extend(self._page(board, payload.get("SearchResult") or {}))
        except HttpError as exc:
            return FetchResult(
                source=self.name,
                board_id=board.board_id or "usajobs",
                success=False,
                complete=False,
                kind=self.kind,
                error=str(exc),
            )
        # Only close disappeared jobs when every page of the result set was read.
        complete = count <= self.page_size * self.max_pages
        return FetchResult(
            source=self.name,
            board_id=board.board_id or "usajobs",
            success=True,
            complete=complete,
            kind=self.kind,
            observations=observations,
            truncated=not complete,
        )

    def _page(self, board: Board, search: dict) -> list[JobObservation]:
        found = []
        for item in search.get("SearchResultItems") or []:
            desc = item.get("MatchedObjectDescriptor") or {}
            title = (desc.get("PositionTitle") or "").strip()
            pos_id = str(desc.get("PositionID") or "")
            if not title or not pos_id:
                continue
            org = (desc.get("OrganizationName") or desc.get("DepartmentName") or board.company).strip()
            apply_url = desc.get("PositionURI") or ""
            if not apply_url:
                apply_uri = desc.get("ApplyURI") or ""
                apply_url = apply_uri[0] if isinstance(apply_uri, list) and apply_uri else apply_uri
            if not isinstance(apply_url, str) or not apply_url:
                apply_url = "https://www.usajobs.gov/"
            loc_list = desc.get("PositionLocation") or []
            loc = loc_list[0] if loc_list else {}
            city = loc.get("CityName") or ""
            region = loc.get("CountrySubDivisionCode") or ""
            country = loc.get("CountryCode") or loc.get("CountryName") or ""
            location_raw = loc.get("LocationName") or ", ".join(part for part in (city, region, country) if part)
            remote = None
            workplace = ""
            if "remote" in location_raw.lower() or (desc.get("PositionRemoteIndicator") is True):
                remote = True
                workplace = "remote"
            pay_min, pay_max, currency, period = _remuneration(desc.get("PositionRemuneration") or [])
            found.append(
                JobObservation(
                    source=self.name,
                    board_id=board.board_id or "usajobs",
                    source_job_id=pos_id,
                    company=org,
                    title=title,
                    apply_url=apply_url,
                    location_raw=location_raw,
                    city="" if isinstance(city, str) and city.lower() == "remote" else city,
                    region=region,
                    country=country,
                    remote=remote,
                    workplace=workplace,
                    pay_min=pay_min,
                    pay_max=pay_max,
                    pay_currency=currency,
                    pay_period=period,
                    department=desc.get("DepartmentName") or "",
                    posted_at=parse_posted(desc.get("PublicationStartDate") or desc.get("PositionStartDate")),
                    sector=board.sector or "government",
                )
            )
        return found


def _remuneration(items: list) -> tuple[float | None, float | None, str, str]:
    if not items:
        return None, None, "", ""
    item = items[0] or {}
    try:
        low = float(item.get("MinimumRange")) if item.get("MinimumRange") not in (None, "") else None
    except (TypeError, ValueError):
        low = None
    try:
        high = float(item.get("MaximumRange")) if item.get("MaximumRange") not in (None, "") else None
    except (TypeError, ValueError):
        high = None
    period_raw = (item.get("RateIntervalCode") or "").lower()
    period = {"pa": "year", "ph": "hour", "pm": "month", "pw": "week", "pd": "day"}.get(period_raw, "year")
    if low == 0 and high == 0:
        return None, None, "", ""
    return low, high, "USD", period
