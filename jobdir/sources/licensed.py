"""Stubs for paid, licensed job feeds.

These adapters do not call vendor APIs. A contract and key are required before
any client is implemented. They never pretend an empty pull is a full board,
so they cannot mark jobs closed.
"""

from __future__ import annotations

import os

from jobdir.http import Client
from jobdir.models import Board, FetchResult


class _LicensedStub:
    name = "licensed"
    env_var = ""
    vendor = ""
    kind = "licensed"

    def fetch(self, board: Board, client: Client) -> FetchResult:
        del client
        key = os.environ.get(self.env_var, "").strip()
        if not key:
            reason = f"{self.env_var} is unset. {self.vendor} is a licensed feed and is not called."
        else:
            reason = (
                f"{self.vendor} key is present, but this build only reserves the adapter. "
                "Wire the licensed client under the vendor contract before enabling it."
            )
        return FetchResult(
            source=self.name,
            board_id=board.board_id or self.name,
            success=True,
            complete=False,
            kind=self.kind,
            skipped=True,
            error=reason,
        )


class CoreSignalAdapter(_LicensedStub):
    name = "coresignal"
    env_var = "CORESIGNAL_API_KEY"
    vendor = "Coresignal"


class LightcastAdapter(_LicensedStub):
    name = "lightcast"
    env_var = "LIGHTCAST_CLIENT_ID"
    vendor = "Lightcast"


class TheirStackAdapter(_LicensedStub):
    name = "theirstack"
    env_var = "THEIRSTACK_API_KEY"
    vendor = "TheirStack"
