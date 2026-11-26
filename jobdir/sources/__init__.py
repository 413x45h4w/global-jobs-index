"""Source adapters. Live boards are fetched; licensed feeds stay stubs."""

from jobdir.sources.ats import (
    AshbyAdapter,
    GreenhouseAdapter,
    LeverAdapter,
    RecruiteeAdapter,
    SmartRecruitersAdapter,
    WorkableAdapter,
    WorkdayAdapter,
)
from jobdir.sources.commoncrawl import CommonCrawlAdapter
from jobdir.sources.licensed import CoreSignalAdapter, LightcastAdapter, TheirStackAdapter
from jobdir.sources.personio import PersonioAdapter
from jobdir.sources.rippling import RipplingAdapter
from jobdir.sources.usajobs import USAJobsAdapter

ADAPTERS = {
    adapter.name: adapter
    for adapter in (
        GreenhouseAdapter(),
        LeverAdapter(),
        AshbyAdapter(),
        WorkableAdapter(),
        SmartRecruitersAdapter(),
        RecruiteeAdapter(),
        WorkdayAdapter(),
        PersonioAdapter(),
        RipplingAdapter(),
        USAJobsAdapter(),
        CommonCrawlAdapter(),
        CoreSignalAdapter(),
        LightcastAdapter(),
        TheirStackAdapter(),
    )
}

__all__ = ["ADAPTERS"]
