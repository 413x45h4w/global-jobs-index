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
        USAJobsAdapter(),
        CommonCrawlAdapter(),
        CoreSignalAdapter(),
        LightcastAdapter(),
        TheirStackAdapter(),
    )
}

__all__ = ["ADAPTERS"]
