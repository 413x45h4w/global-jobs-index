"""Rippling public board: https://api.rippling.com/platform/api/ats/v1/board/{token}/jobs"""

from __future__ import annotations

from jobdir.http import Client, HttpError
from jobdir.models import Board, FetchResult, JobObservation
from jobdir.sources.ats import _fail


class RipplingAdapter:
    name = "rippling"
    kind = "live_board"

    def fetch(self, board: Board, client: Client) -> FetchResult:
        url = f"https://api.rippling.com/platform/api/ats/v1/board/{board.board_id}/jobs"
        try:
            payload = client.get_json(url, timeout=90)
        except HttpError as exc:
            return _fail(board, exc)
        if isinstance(payload, dict):
            jobs = payload.get("jobs") or payload.get("items") or []
        else:
            jobs = payload or []
        observations = []
        for job in jobs:
            title = (job.get("name") or job.get("title") or "").strip()
            source_id = str(job.get("uuid") or job.get("id") or "")
            if not title or not source_id:
                continue
            department = job.get("department") or {}
            location = job.get("workLocation") or {}
            label = ""
            if isinstance(location, dict):
                label = location.get("label") or location.get("name") or ""
            elif isinstance(location, str):
                label = location
            dept = ""
            if isinstance(department, dict):
                dept = department.get("label") or department.get("id") or ""
            workplace = "remote" if "remote" in label.lower() else ""
            observations.append(
                JobObservation(
                    source=self.name,
                    board_id=board.board_id,
                    source_job_id=source_id,
                    company=board.company,
                    title=title,
                    apply_url=job.get("url") or f"https://ats.rippling.com/{board.board_id}/jobs/{source_id}",
                    location_raw=label,
                    workplace=workplace,
                    department=dept,
                    sector=board.sector or "",
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
