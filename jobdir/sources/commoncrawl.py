"""Sample schema.org JobPosting JSON-LD from a Common Crawl CDX index.

The default path fetches a small number of WARC records. The full crawl is a
resumable loop over CDX pages; see README and `python -m jobdir cc-run`.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from urllib.parse import urlencode

from jobdir.http import Client, HttpError
from jobdir.models import Board, FetchResult
from jobdir.sources.jsonld import observations_from_html

COLLINFO = "https://index.commoncrawl.org/collinfo.json"
DATA_ROOT = "https://data.commoncrawl.org/"

# Concrete prefixes. A bare "*" query 404s on the current CDX server, and a
# domain-wide wildcard often times out. Prefix match keeps the sample bounded.
DEFAULT_PATTERNS = (
    "jobs.ashbyhq.com/kalshi",
    "jobs.ashbyhq.com/polymarket",
    "jobs.ashbyhq.com/openai",
    "jobs.ashbyhq.com/cursor",
)


@dataclass
class CrawlRecord:
    url: str
    filename: str
    offset: int
    length: int
    timestamp: str = ""


class CommonCrawlAdapter:
    name = "commoncrawl"
    kind = "snapshot"

    def __init__(self, records: int = 30, patterns: tuple[str, ...] = DEFAULT_PATTERNS):
        self.records = records
        self.patterns = patterns

    def fetch(self, board: Board, client: Client) -> FetchResult:
        try:
            crawl_id, cdx = latest_crawl(client)
            wanted = max(1, self.records)
            per_pattern = max(1, wanted // len(self.patterns))
            records: list[CrawlRecord] = []
            errors = 0
            for pattern in self.patterns:
                try:
                    records.extend(cdx_records(client, cdx, pattern, limit=per_pattern))
                except (HttpError, TimeoutError, OSError) as exc:
                    errors += 1
                    continue
                if len(records) >= wanted:
                    break
            records = records[:wanted]
            observations = []
            for record in records:
                try:
                    html = fetch_warc_html(client, record)
                except (HttpError, OSError, ValueError, gzip.BadGzipFile, EOFError):
                    errors += 1
                    continue
                observations.extend(observations_from_html(html, record.url))
            note = f"crawl={crawl_id} records={len(records)} jsonld_jobs={len(observations)} fetch_errors={errors}"
            return FetchResult(
                source=self.name,
                board_id=board.board_id or "commoncrawl",
                success=True,
                complete=False,
                kind=self.kind,
                observations=observations,
                error=note,
            )
        except Exception as exc:  # noqa: BLE001 - one source must not abort the run
            return FetchResult(
                source=self.name,
                board_id=board.board_id or "commoncrawl",
                success=False,
                complete=False,
                kind=self.kind,
                error=f"{type(exc).__name__}: {exc}",
            )


def latest_crawl(client: Client) -> tuple[str, str]:
    payload = client.get_json(COLLINFO, timeout=60)
    if not payload:
        raise RuntimeError("Common Crawl collinfo returned no crawls")
    newest = payload[0]
    return newest["id"], newest["cdx-api"]


def cdx_records(client: Client, cdx_api: str, pattern: str, limit: int) -> list[CrawlRecord]:
    query = urlencode(
        {
            "url": pattern,
            "matchType": "prefix",
            "output": "json",
            "fl": "url,filename,offset,length,status,mime,timestamp",
            "filter": "status:200",
            "limit": str(limit),
        }
    )
    url = f"{cdx_api}?{query}"
    _status, _headers, body = client.request("GET", url, timeout=90)
    records = []
    for line in body.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("status") not in (None, "200", 200):
            continue
        mime = (row.get("mime") or "")
        if mime and "html" not in mime:
            continue
        if not row.get("filename") or row.get("offset") in (None, "") or row.get("length") in (None, ""):
            continue
        records.append(
            CrawlRecord(
                url=row.get("url") or "",
                filename=row["filename"],
                offset=int(row["offset"]),
                length=int(row["length"]),
                timestamp=str(row.get("timestamp") or ""),
            )
        )
    return records


def fetch_warc_html(client: Client, record: CrawlRecord) -> str:
    end = record.offset + record.length - 1
    _status, _headers, blob = client.request(
        "GET",
        DATA_ROOT + record.filename,
        headers={"Range": f"bytes={record.offset}-{end}"},
        timeout=60,
    )
    if blob[:2] == b"\x1f\x8b":
        raw = gzip.decompress(blob)
    else:
        raw = blob
    return _html_from_warc(raw)


def _html_from_warc(raw: bytes) -> str:
    header_end = raw.find(b"\r\n\r\n")
    if header_end == -1:
        header_end = raw.find(b"\n\n")
        sep = 2
    else:
        sep = 4
    payload = raw[header_end + sep :] if header_end != -1 else raw
    if payload.startswith(b"HTTP/"):
        body_at = payload.find(b"\r\n\r\n")
        if body_at == -1:
            body_at = payload.find(b"\n\n")
            payload = payload[body_at + 2 :] if body_at != -1 else payload
        else:
            payload = payload[body_at + 4 :]
    # Some records gzip the HTTP body a second time.
    if payload[:2] == b"\x1f\x8b":
        try:
            payload = gzip.decompress(payload)
        except gzip.BadGzipFile:
            pass
    return payload.decode("utf-8", "replace")


def cdx_page_count(client: Client, cdx_api: str, pattern: str) -> int:
    url = f"{cdx_api}?url={pattern}&showNumPages=true"
    payload = client.get_json(url, timeout=120)
    if isinstance(payload, dict):
        return int(payload.get("pages") or 0)
    return 0
