"""Personio public XML feed: https://{token}.jobs.personio.de/xml"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from jobdir.http import Client, HttpError
from jobdir.models import Board, FetchResult, JobObservation
from jobdir.normalize import parse_posted
from jobdir.sources.ats import _fail

_DESCRIPTIONS = re.compile(r"<jobDescriptions>.*?</jobDescriptions>", re.S)


def positions_from_xml(xml_text: str) -> list[dict]:
    cleaned = _DESCRIPTIONS.sub("", xml_text)
    root = ET.fromstring(cleaned)
    rows = []
    for node in root.iter("position"):
        rows.append(
            {
                "id": _text(node, "id"),
                "title": _text(node, "name"),
                "company": _text(node, "subcompany"),
                "office": _text(node, "office"),
                "department": _text(node, "department"),
                "employment_type": _text(node, "employmentType"),
                "schedule": _text(node, "schedule"),
                "created_at": _text(node, "createdAt"),
                "extra_offices": [el.text or "" for el in node.findall("./additionalOffices/office")],
            }
        )
    return rows


def _text(node, tag: str) -> str:
    child = node.find(tag)
    return (child.text or "").strip() if child is not None and child.text else ""


class PersonioAdapter:
    name = "personio"
    kind = "live_board"

    def fetch(self, board: Board, client: Client) -> FetchResult:
        url = f"https://{board.board_id}.jobs.personio.de/xml"
        try:
            _status, _headers, body = client.request("GET", url, timeout=90, headers={"Accept": "application/xml, text/xml, */*"})
        except HttpError as exc:
            return _fail(board, exc)
        try:
            positions = positions_from_xml(body.decode("utf-8", "replace"))
        except ET.ParseError as exc:
            return _fail(board, exc)
        observations = []
        for job in positions:
            if not job["id"] or not job["title"]:
                continue
            office = job["office"]
            extra = " ".join(job["extra_offices"])
            blob = f"{office} {extra}".lower()
            workplace = ""
            if "remote" in blob and office and "remote" not in office.lower():
                workplace = "hybrid"
            elif "remote" in blob:
                workplace = "remote"
            observations.append(
                JobObservation(
                    source=self.name,
                    board_id=board.board_id,
                    source_job_id=job["id"],
                    company=job["company"] or board.company,
                    title=job["title"],
                    apply_url=f"https://{board.board_id}.jobs.personio.de/job/{job['id']}",
                    location_raw=office,
                    workplace=workplace,
                    department=job["department"],
                    employment_type=job["employment_type"] or job["schedule"],
                    posted_at=parse_posted(job["created_at"]),
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
