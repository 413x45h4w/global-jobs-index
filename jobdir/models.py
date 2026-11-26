"""Shared records passed between adapters, storage, and export."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Board:
    company: str
    source: str
    board_id: str
    sector: str = "other"
    careers_url: str = ""
    api_base: str = ""
    workday_host: str = ""
    workday_tenant: str = ""
    workday_site: str = ""
    expected_count: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return (self.source, self.board_id)


@dataclass
class JobObservation:
    """One normalized sighting of a single source listing."""

    source: str
    board_id: str
    source_job_id: str
    company: str
    title: str
    apply_url: str
    location_raw: str = ""
    city: str = ""
    region: str = ""
    country: str = ""
    remote: bool | None = None
    workplace: str = ""  # remote, hybrid, onsite, ""
    pay_min: float | None = None
    pay_max: float | None = None
    pay_currency: str = ""
    pay_period: str = ""  # year, month, hour, week, day
    department: str = ""
    employment_type: str = ""
    posted_at: str = ""  # YYYY-MM-DD when known
    sector: str = ""


@dataclass
class FetchResult:
    source: str
    board_id: str
    success: bool
    complete: bool
    kind: str = "live_board"  # live_board | snapshot | licensed
    skipped: bool = False
    error: str = ""
    observations: list[JobObservation] = field(default_factory=list)
    truncated: bool = False
