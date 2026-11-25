"""Public ATS job-board adapters. No login, no HTML scraping of third-party boards."""

from __future__ import annotations

from jobdir.http import Client, HttpError
from jobdir.models import Board, FetchResult, JobObservation
from jobdir.normalize import parse_pay_text, parse_posted

LIVE = "live_board"


def _fail(board: Board, exc: Exception) -> FetchResult:
    return FetchResult(
        source=board.source,
        board_id=board.board_id,
        success=False,
        complete=False,
        kind=LIVE,
        error=f"{type(exc).__name__}: {exc}",
    )


def _base_obs(board: Board, **kwargs) -> JobObservation:
    data = {
        "source": board.source,
        "board_id": board.board_id,
        "company": board.company,
        "sector": board.sector or "",
    }
    data.update(kwargs)
    return JobObservation(**data)


class GreenhouseAdapter:
    name = "greenhouse"
    kind = LIVE

    def fetch(self, board: Board, client: Client) -> FetchResult:
        url = f"https://boards-api.greenhouse.io/v1/boards/{board.board_id}/jobs"
        try:
            payload = client.get_json(url, timeout=120)
        except HttpError as exc:
            return _fail(board, exc)
        jobs = payload.get("jobs") or []
        observations = []
        for job in jobs:
            title = (job.get("title") or "").strip()
            if not title:
                continue
            location = (job.get("location") or {}).get("name") or ""
            meta = job.get("metadata") or []
            department = ""
            workplace = ""
            for item in meta:
                name = (item.get("name") or "").lower()
                value = item.get("value")
                if isinstance(value, str) and any(word in name for word in ("department", "team", "division")) and not department:
                    department = value.strip()
                if isinstance(value, str) and "workplace" in name:
                    workplace = value.strip().lower()
            pay_min, pay_max, currency, period = None, None, "", ""
            for item in meta:
                name = (item.get("name") or "").lower()
                if any(word in name for word in ("pay", "salary", "comp")):
                    pay_min, pay_max, currency, period = parse_pay_text(str(item.get("value") or ""))
                    if pay_min is not None:
                        break
            observations.append(
                _base_obs(
                    board,
                    company=(job.get("company_name") or board.company or "").strip() or board.company,
                    source_job_id=str(job.get("id") or ""),
                    title=title,
                    apply_url=job.get("absolute_url") or "",
                    location_raw=location,
                    workplace=workplace if workplace in {"remote", "hybrid", "onsite"} else "",
                    department=department,
                    posted_at=parse_posted(job.get("first_published") or job.get("updated_at")),
                    pay_min=pay_min,
                    pay_max=pay_max,
                    pay_currency=currency,
                    pay_period=period,
                )
            )
        return FetchResult(
            source=self.name,
            board_id=board.board_id,
            success=True,
            complete=True,
            kind=self.kind,
            observations=observations,
        )


class LeverAdapter:
    name = "lever"
    kind = LIVE

    def fetch(self, board: Board, client: Client) -> FetchResult:
        base = (board.api_base or "https://api.lever.co").rstrip("/")
        url = f"{base}/v0/postings/{board.board_id}?mode=json"
        try:
            payload = client.get_json(url, timeout=120)
        except HttpError as exc:
            return _fail(board, exc)
        if isinstance(payload, dict):
            postings = payload.get("postings") or payload.get("data") or []
        else:
            postings = payload or []
        observations = []
        for job in postings:
            title = (job.get("text") or "").strip()
            if not title:
                continue
            categories = job.get("categories") or {}
            workplace = (job.get("workplaceType") or "").lower()
            salary = job.get("salaryRange") or job.get("salaryDescription") or ""
            pay_min = pay_max = None
            currency = period = ""
            if isinstance(salary, dict):
                pay_min = _num(salary.get("min"))
                pay_max = _num(salary.get("max"))
                currency = (salary.get("currency") or "").upper()
                period = _period(salary.get("interval") or salary.get("intervalType") or "")
            if pay_min is None:
                pay_min, pay_max, currency, period = parse_pay_text(job.get("additionalPlain") or "")
            observations.append(
                _base_obs(
                    board,
                    source_job_id=str(job.get("id") or ""),
                    title=title,
                    apply_url=job.get("hostedUrl") or job.get("applyUrl") or "",
                    location_raw=categories.get("location") or "",
                    country=job.get("country") or "",
                    workplace=workplace if workplace in {"remote", "hybrid", "onsite"} else "",
                    department=categories.get("department") or categories.get("team") or "",
                    employment_type=categories.get("commitment") or "",
                    posted_at=parse_posted(job.get("createdAt")),
                    pay_min=pay_min,
                    pay_max=pay_max,
                    pay_currency=currency,
                    pay_period=period,
                )
            )
        return FetchResult(
            source=self.name,
            board_id=board.board_id,
            success=True,
            complete=True,
            kind=self.kind,
            observations=observations,
        )


class AshbyAdapter:
    name = "ashby"
    kind = LIVE

    def fetch(self, board: Board, client: Client) -> FetchResult:
        url = (
            "https://api.ashbyhq.com/posting-api/job-board/"
            f"{board.board_id}?includeCompensation=true"
        )
        try:
            payload = client.get_json(url, timeout=120)
        except HttpError as exc:
            return _fail(board, exc)
        observations = []
        for job in payload.get("jobs") or []:
            if job.get("isListed") is False:
                continue
            title = (job.get("title") or "").strip()
            if not title:
                continue
            address = ((job.get("address") or {}).get("postalAddress") or {})
            workplace = (job.get("workplaceType") or "").lower()
            mapped = {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite"}.get(workplace, "")
            if job.get("isRemote") is True and not mapped:
                mapped = "remote"
            pay_min, pay_max, currency, period = _ashby_pay(job.get("compensation") or {})
            observations.append(
                _base_obs(
                    board,
                    source_job_id=str(job.get("id") or ""),
                    title=title,
                    apply_url=job.get("jobUrl") or job.get("applyUrl") or "",
                    location_raw=job.get("location") or "",
                    city=address.get("addressLocality") or "",
                    region=address.get("addressRegion") or "",
                    country=address.get("addressCountry") or "",
                    remote=True if mapped == "remote" else (False if mapped else None),
                    workplace=mapped,
                    department=job.get("department") or job.get("team") or "",
                    employment_type=job.get("employmentType") or "",
                    posted_at=parse_posted(job.get("publishedAt")),
                    pay_min=pay_min,
                    pay_max=pay_max,
                    pay_currency=currency,
                    pay_period=period,
                )
            )
        return FetchResult(
            source=self.name,
            board_id=board.board_id,
            success=True,
            complete=True,
            kind=self.kind,
            observations=observations,
        )


class WorkableAdapter:
    name = "workable"
    kind = LIVE

    def fetch(self, board: Board, client: Client) -> FetchResult:
        url = f"https://apply.workable.com/api/v1/widget/accounts/{board.board_id}"
        try:
            payload = client.get_json(url, timeout=90)
        except HttpError as exc:
            return _fail(board, exc)
        company = (payload.get("name") or board.company or "").strip()
        observations = []
        for job in payload.get("jobs") or []:
            title = (job.get("title") or "").strip()
            shortcode = str(job.get("shortcode") or job.get("id") or "")
            if not title or not shortcode:
                continue
            locations = job.get("locations") or []
            primary = next((loc for loc in locations if isinstance(loc, dict) and not loc.get("hidden")), {})
            tele = bool(job.get("telecommuting"))
            workplace = "remote" if tele else ""
            observations.append(
                _base_obs(
                    board,
                    source_job_id=shortcode,
                    company=company or board.company,
                    title=title,
                    apply_url=job.get("url") or job.get("application_url") or job.get("shortlink") or "",
                    location_raw=", ".join(
                        part for part in (job.get("city"), job.get("state") or job.get("region"), job.get("country")) if part
                    ),
                    city=(primary.get("city") or job.get("city") or "") if isinstance(primary, dict) else (job.get("city") or ""),
                    region=(primary.get("region") or job.get("state") or "") if isinstance(primary, dict) else (job.get("state") or ""),
                    country=(primary.get("country") or job.get("country") or "") if isinstance(primary, dict) else (job.get("country") or ""),
                    remote=True if tele else False,
                    workplace=workplace,
                    department=job.get("department") or "",
                    employment_type=job.get("employment_type") or "",
                    posted_at=parse_posted(job.get("published_on") or job.get("created_at")),
                )
            )
        return FetchResult(
            source=self.name,
            board_id=board.board_id,
            success=True,
            complete=True,
            kind=self.kind,
            observations=observations,
        )


class SmartRecruitersAdapter:
    name = "smartrecruiters"
    kind = LIVE

    def fetch(self, board: Board, client: Client) -> FetchResult:
        observations = []
        offset = 0
        total = None
        try:
            while True:
                url = (
                    "https://api.smartrecruiters.com/v1/companies/"
                    f"{board.board_id}/postings?limit=100&offset={offset}"
                )
                payload = client.get_json(url, timeout=60)
                if total is None:
                    total = int(payload.get("totalFound") or 0)
                batch = payload.get("content") or []
                if not batch:
                    break
                for job in batch:
                    title = (job.get("name") or "").strip()
                    job_id = str(job.get("id") or job.get("uuid") or "")
                    if not title or not job_id:
                        continue
                    company = ((job.get("company") or {}).get("name") or board.company).strip()
                    identifier = (job.get("company") or {}).get("identifier") or board.board_id
                    location = job.get("location") or {}
                    remote = bool(location.get("remote"))
                    hybrid = bool(location.get("hybrid"))
                    workplace = "remote" if remote else ("hybrid" if hybrid else "onsite")
                    department = ""
                    dept = job.get("department") or {}
                    if isinstance(dept, dict):
                        department = dept.get("label") or ""
                    function = job.get("function") or {}
                    if not department and isinstance(function, dict):
                        department = function.get("label") or ""
                    observations.append(
                        _base_obs(
                            board,
                            source_job_id=job_id,
                            company=company or board.company,
                            title=title,
                            apply_url=f"https://jobs.smartrecruiters.com/{identifier}/{job_id}",
                            location_raw=location.get("fullLocation") or "",
                            city=location.get("city") or "",
                            region=location.get("region") or "",
                            country=location.get("country") or "",
                            remote=True if remote else False,
                            workplace=workplace,
                            department=department,
                            employment_type=(job.get("typeOfEmployment") or {}).get("label") or "",
                            posted_at=parse_posted(job.get("releasedDate")),
                        )
                    )
                offset += len(batch)
                if offset >= total or len(batch) < 100:
                    break
        except HttpError as exc:
            return _fail(board, exc)
        complete = total is not None and len(observations) >= total
        # A short final page also means the feed was fully read.
        if total is not None and offset >= total:
            complete = True
        return FetchResult(
            source=self.name,
            board_id=board.board_id,
            success=True,
            complete=complete,
            kind=self.kind,
            observations=observations,
        )


class RecruiteeAdapter:
    name = "recruitee"
    kind = LIVE

    def fetch(self, board: Board, client: Client) -> FetchResult:
        url = f"https://{board.board_id}.recruitee.com/api/offers/"
        try:
            payload = client.get_json(url, timeout=90)
        except HttpError as exc:
            return _fail(board, exc)
        observations = []
        for job in payload.get("offers") or []:
            title = (job.get("title") or "").strip()
            source_id = str(job.get("id") or job.get("guid") or job.get("slug") or "")
            if not title or not source_id:
                continue
            salary = job.get("salary") or {}
            remote = job.get("remote")
            hybrid = bool(job.get("hybrid"))
            on_site = job.get("on_site")
            if remote is True:
                workplace = "remote"
            elif hybrid:
                workplace = "hybrid"
            elif on_site is True:
                workplace = "onsite"
            else:
                workplace = ""
            observations.append(
                _base_obs(
                    board,
                    source_job_id=source_id,
                    company=(job.get("company_name") or board.company).strip(),
                    title=title,
                    apply_url=job.get("careers_apply_url") or job.get("careers_url") or "",
                    location_raw=job.get("location") or "",
                    city=job.get("city") or "",
                    region=job.get("state_name") or "",
                    country=job.get("country_code") or job.get("country") or "",
                    remote=True if remote is True else (False if remote is False else None),
                    workplace=workplace,
                    department=job.get("department") or "",
                    employment_type=job.get("employment_type_code") or "",
                    posted_at=parse_posted(job.get("published_at") or job.get("created_at")),
                    pay_min=_num(salary.get("min")),
                    pay_max=_num(salary.get("max")),
                    pay_currency=(salary.get("currency") or "").upper(),
                    pay_period=_period(salary.get("period") or ""),
                )
            )
        return FetchResult(
            source=self.name,
            board_id=board.board_id,
            success=True,
            complete=True,
            kind=self.kind,
            observations=observations,
        )


class WorkdayAdapter:
    """Workday CXS search.

    Some tenants paginate through their whole catalog. Others wrap back to the
    first page once `offset` passes a cap (often 2,000) even when facet counts
    show more jobs. When that happens, the same search is repeated once per
    facet value so each bucket stays under the cap.
    """

    name = "workday"
    kind = LIVE
    page_size = 20
    max_pages = 3500
    max_requests = 4000

    def fetch(self, board: Board, client: Client) -> FetchResult:
        if not (board.workday_host and board.workday_tenant and board.workday_site):
            return FetchResult(
                source=self.name,
                board_id=board.board_id,
                success=False,
                complete=False,
                kind=self.kind,
                error="workday board is missing host, tenant, or site",
            )
        url = (
            f"https://{board.workday_host}/wday/cxs/"
            f"{board.workday_tenant}/{board.workday_site}/jobs"
        )
        seen: set[str] = set()
        budget = {"n": 0}
        jobs: list = []
        try:
            jobs, facets, wrapped, truncated = self._paginate(client, url, {}, seen, budget)
            facet_total = _facet_coverage(facets)
            if wrapped and facet_total > len(jobs) + self.page_size:
                more, split_truncated = self._split(client, url, facets, seen, budget, depth=0)
                jobs.extend(more)
                truncated = truncated or split_truncated
                wrapped = bool(split_truncated)
            elif wrapped and facets and 0 < facet_total <= len(jobs) + self.page_size:
                wrapped = False
            complete = not truncated and not wrapped
        except HttpError as exc:
            if jobs:
                observations = [obs for job in jobs if (obs := self._one(board, job))]
                return self._result(board, observations, complete=False, truncated=True, error=str(exc))
            return _fail(board, exc)
        observations = [obs for job in jobs if (obs := self._one(board, job))]
        note = ""
        if not complete:
            note = f"workday partial unique={len(observations)} requests={budget['n']}"
        return self._result(board, observations, complete=complete, truncated=not complete, error=note)

    def _result(self, board, observations, complete, truncated, error="", seen_jobs=None):
        return FetchResult(
            source=self.name,
            board_id=board.board_id,
            success=True,
            complete=complete,
            kind=self.kind,
            observations=observations,
            truncated=truncated,
            error=error,
        )

    def _paginate(self, client, url, facets, seen, budget):
        """Page one facet selection.

        `seen` is the set of ids already stored for this board. A page that only
        repeats ids from earlier offsets of *this* walk is a cap wrap. Ids that
        were found by a previous walk are skipped but do not stop paging, so a
        facet split can continue past the jobs the capped walk already kept.
        """
        collected = []
        facets_out = None
        wrapped = False
        truncated = False
        offset = 0
        pages = 0
        local: set[str] = set()
        while pages < self.max_pages:
            if budget["n"] >= self.max_requests:
                truncated = True
                break
            budget["n"] += 1
            payload = client.post_json(
                url,
                {"appliedFacets": facets, "limit": self.page_size, "offset": offset, "searchText": ""},
                timeout=60,
            )
            if facets_out is None:
                facets_out = payload.get("facets")
            batch = payload.get("jobPostings") or []
            if not batch:
                break
            page_ids = [job_id for job in batch if (job_id := _workday_id(job))]
            if page_ids and all(job_id in local for job_id in page_ids):
                wrapped = True
                break
            for job in batch:
                job_id = _workday_id(job)
                if not job_id or job_id in local:
                    continue
                local.add(job_id)
                if job_id in seen:
                    continue
                seen.add(job_id)
                collected.append(job)
            pages += 1
            if len(batch) < self.page_size:
                break
            offset += len(batch)
        else:
            truncated = True
        if budget["n"] >= self.max_requests:
            truncated = True
        return collected, facets_out, wrapped, truncated

    def _split(self, client, url, facets, seen, budget, depth):
        choice = _pick_split_facet(facets, len(seen))
        if not choice or depth > 1:
            return [], True
        param, values = choice
        collected = []
        truncated = False
        for value in values:
            count = value.get("count") or 0
            if count <= 0 or not value.get("id"):
                continue
            if budget["n"] >= self.max_requests:
                truncated = True
                break
            jobs, child_facets, wrapped, hit_budget = self._paginate(
                client, url, {param: [value["id"]]}, seen, budget
            )
            collected.extend(jobs)
            truncated = truncated or hit_budget
            child_total = _facet_coverage(child_facets)
            if wrapped and child_total > count and depth < 1:
                more, child_truncated = self._split(client, url, child_facets, seen, budget, depth + 1)
                collected.extend(more)
                truncated = truncated or child_truncated
            elif wrapped and len(jobs) + self.page_size < count:
                truncated = True
        return collected, truncated

    def _one(self, board: Board, job: dict) -> JobObservation | None:
        title = (job.get("title") or "").strip()
        path = job.get("externalPath") or ""
        if not title or not path:
            return None
        source_id = _workday_id(job) or path
        apply_url = f"https://{board.workday_host}/en-US/{board.workday_site}{path}"
        location = job.get("locationsText") or ""
        workplace = "remote" if "remote" in location.lower() else ""
        return _base_obs(
            board,
            source_job_id=source_id,
            title=title,
            apply_url=apply_url,
            location_raw=location,
            workplace=workplace,
            posted_at=parse_posted(job.get("postedOn")),
        )


def _workday_id(job: dict) -> str:
    path = job.get("externalPath") or ""
    if path:
        return path
    bullet = job.get("bulletFields") or []
    return str(bullet[0]) if bullet else ""


def _facet_values(facets) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for facet in facets or []:
        values = facet.get("values") or []
        nested = values and isinstance(values[0], dict) and "values" in values[0] and "id" not in values[0]
        if nested:
            for child in values:
                param = child.get("facetParameter") or facet.get("facetParameter") or ""
                grouped.setdefault(param, []).extend(v for v in (child.get("values") or []) if v.get("id"))
            continue
        param = facet.get("facetParameter") or ""
        grouped.setdefault(param, []).extend(v for v in values if v.get("id"))
    return grouped


def _facet_coverage(facets) -> int:
    best = 0
    for values in _facet_values(facets).values():
        best = max(best, sum(v.get("count") or 0 for v in values))
    return best


def _pick_split_facet(facets, already: int) -> tuple[str, list[dict]] | None:
    """Pick a facet whose buckets sum to more jobs than the capped page walk found."""
    best = None
    for param, values in _facet_values(facets).items():
        usable = [v for v in values if (v.get("count") or 0) > 0]
        if len(usable) < 2:
            continue
        total = sum(v.get("count") or 0 for v in usable)
        if total <= already + 20:
            continue
        max_bucket = max(v.get("count") or 0 for v in usable)
        score = (total, -max_bucket, -len(usable))
        if best is None or score > best[0]:
            best = (score, param, usable)
    if not best:
        return None
    return best[1], best[2]


def _num(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number


def _period(value: str) -> str:
    text = (value or "").lower()
    if "hour" in text:
        return "hour"
    if "month" in text:
        return "month"
    if "week" in text:
        return "week"
    if "day" in text and "today" not in text:
        return "day"
    if "year" in text or "annual" in text:
        return "year"
    return "year" if text else ""


def _ashby_pay(compensation: dict) -> tuple[float | None, float | None, str, str]:
    components = list(compensation.get("summaryComponents") or [])
    if not components:
        for tier in compensation.get("compensationTiers") or []:
            components.extend(tier.get("components") or [])
    salary = next(
        (item for item in components if (item.get("compensationType") or "").lower() == "salary"),
        components[0] if components else None,
    )
    if not salary:
        return None, None, "", ""
    return (
        _num(salary.get("minValue")),
        _num(salary.get("maxValue")),
        (salary.get("currencyCode") or "").upper(),
        _period(salary.get("interval") or ""),
    )
