"""SQLite store. Observations are insert-only; listings and jobs are projections."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from jobdir.models import FetchResult, JobObservation
from jobdir.normalize import finalize_observation, job_id_for, location_key, norm_company, norm_title, observation_payload

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  stats_json TEXT
);

CREATE TABLE IF NOT EXISTS run_boards (
  run_id INTEGER NOT NULL,
  source TEXT NOT NULL,
  board_id TEXT NOT NULL,
  success INTEGER NOT NULL,
  complete INTEGER NOT NULL,
  skipped INTEGER NOT NULL,
  jobs_seen INTEGER NOT NULL,
  error TEXT,
  PRIMARY KEY (run_id, source, board_id)
);

CREATE TABLE IF NOT EXISTS listings (
  listing_key TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  board_id TEXT NOT NULL,
  source_job_id TEXT NOT NULL,
  job_id TEXT NOT NULL,
  company TEXT NOT NULL,
  title TEXT NOT NULL,
  location_raw TEXT,
  city TEXT,
  region TEXT,
  country TEXT,
  remote INTEGER,
  workplace TEXT,
  pay_min REAL,
  pay_max REAL,
  pay_currency TEXT,
  pay_period TEXT,
  department TEXT,
  employment_type TEXT,
  posted_at TEXT,
  apply_url TEXT NOT NULL,
  sector TEXT,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  status TEXT NOT NULL,
  closed_at TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
  job_id TEXT PRIMARY KEY,
  company TEXT NOT NULL,
  company_norm TEXT NOT NULL,
  title TEXT NOT NULL,
  title_norm TEXT NOT NULL,
  location_key TEXT NOT NULL,
  location_raw TEXT,
  city TEXT,
  region TEXT,
  country TEXT,
  remote INTEGER,
  workplace TEXT,
  pay_min REAL,
  pay_max REAL,
  pay_currency TEXT,
  pay_period TEXT,
  department TEXT,
  employment_type TEXT,
  posted_at TEXT,
  apply_url TEXT NOT NULL,
  sector TEXT,
  sources TEXT NOT NULL,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  status TEXT NOT NULL,
  closed_at TEXT
);

CREATE TABLE IF NOT EXISTS observations (
  id INTEGER PRIMARY KEY,
  run_id INTEGER,
  observed_at TEXT NOT NULL,
  listing_key TEXT NOT NULL,
  job_id TEXT NOT NULL,
  source TEXT NOT NULL,
  board_id TEXT NOT NULL,
  event TEXT NOT NULL,
  payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_listings_board ON listings(source, board_id, status);
CREATE INDEX IF NOT EXISTS idx_listings_job ON listings(job_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_obs_listing ON observations(listing_key);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _remote_int(value: bool | None) -> int | None:
    if value is None:
        return None
    return 1 if value else 0


class Store:
    def __init__(self, path: str):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=DELETE")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()

    def vacuum(self) -> None:
        self.conn.commit()
        self.conn.execute("VACUUM")

    def start_run(self) -> int:
        cur = self.conn.execute("INSERT INTO runs (started_at) VALUES (?)", (utc_now(),))
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, stats: dict) -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at = ?, stats_json = ? WHERE id = ?",
            (utc_now(), json.dumps(stats), run_id),
        )
        self.conn.commit()

    def apply(self, run_id: int, result: FetchResult, observed_at: str | None = None) -> dict:
        observed_at = observed_at or utc_now()
        summary = {
            "source": result.source,
            "board_id": result.board_id,
            "success": result.success,
            "seen": 0,
            "closed": 0,
            "error": result.error,
        }
        if result.skipped or not result.success:
            self._record_board(run_id, result, 0)
            self.conn.commit()
            return summary

        touched: set[str] = set()
        seen: set[str] = set()
        with self.conn:
            for obs in result.observations:
                if not obs.title or not obs.company or not obs.apply_url or not obs.source_job_id:
                    continue
                obs, job_id, _loc = finalize_observation(obs)
                listing_key = f"{obs.source}|{obs.board_id}|{obs.source_job_id}"
                if listing_key in seen:
                    continue
                seen.add(listing_key)
                previous = self.conn.execute(
                    "SELECT job_id, first_seen FROM listings WHERE listing_key = ?",
                    (listing_key,),
                ).fetchone()
                first_seen = previous["first_seen"] if previous else observed_at
                if previous and previous["job_id"] != job_id:
                    touched.add(previous["job_id"])
                touched.add(job_id)
                self._upsert_listing(obs, listing_key, job_id, first_seen, observed_at)
                self._insert_observation(run_id, observed_at, listing_key, job_id, obs, "seen")

            closed = 0
            if result.complete and result.kind == "live_board":
                closed_rows = self._close_missing(result.source, result.board_id, seen, observed_at, run_id)
                closed = len(closed_rows)
                for row in closed_rows:
                    touched.add(row["job_id"])
            for job_id in touched:
                self._recompute_job(job_id)
            self._record_board(run_id, result, len(seen))
        summary["seen"] = len(seen)
        summary["closed"] = closed
        return summary

    def _upsert_listing(self, obs: JobObservation, listing_key: str, job_id: str, first_seen: str, observed_at: str) -> None:
        self.conn.execute(
            """
            INSERT INTO listings (
              listing_key, source, board_id, source_job_id, job_id, company, title,
              location_raw, city, region, country, remote, workplace,
              pay_min, pay_max, pay_currency, pay_period, department, employment_type,
              posted_at, apply_url, sector, first_seen, last_seen, status, closed_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'open', NULL)
            ON CONFLICT(listing_key) DO UPDATE SET
              job_id=excluded.job_id,
              company=excluded.company,
              title=excluded.title,
              location_raw=excluded.location_raw,
              city=excluded.city,
              region=excluded.region,
              country=excluded.country,
              remote=excluded.remote,
              workplace=excluded.workplace,
              pay_min=excluded.pay_min,
              pay_max=excluded.pay_max,
              pay_currency=excluded.pay_currency,
              pay_period=excluded.pay_period,
              department=excluded.department,
              employment_type=excluded.employment_type,
              posted_at=excluded.posted_at,
              apply_url=excluded.apply_url,
              sector=excluded.sector,
              last_seen=excluded.last_seen,
              status='open',
              closed_at=NULL
            """,
            (
                listing_key,
                obs.source,
                obs.board_id,
                obs.source_job_id,
                job_id,
                obs.company,
                obs.title,
                obs.location_raw,
                obs.city,
                obs.region,
                obs.country,
                _remote_int(obs.remote),
                obs.workplace,
                obs.pay_min,
                obs.pay_max,
                obs.pay_currency,
                obs.pay_period,
                obs.department,
                obs.employment_type,
                obs.posted_at,
                obs.apply_url,
                obs.sector,
                first_seen,
                observed_at,
            ),
        )

    def _insert_observation(
        self,
        run_id: int,
        observed_at: str,
        listing_key: str,
        job_id: str,
        obs: JobObservation,
        event: str,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO observations (
              run_id, observed_at, listing_key, job_id, source, board_id, event, payload_json
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                observed_at,
                listing_key,
                job_id,
                obs.source,
                obs.board_id,
                event,
                json.dumps(observation_payload(obs), separators=(",", ":")),
            ),
        )

    def _close_missing(self, source: str, board_id: str, seen: set[str], observed_at: str, run_id: int) -> list[sqlite3.Row]:
        self.conn.execute("DROP TABLE IF EXISTS _seen")
        self.conn.execute("CREATE TEMP TABLE _seen (k TEXT PRIMARY KEY)")
        if seen:
            self.conn.executemany("INSERT INTO _seen (k) VALUES (?)", [(key,) for key in seen])
        rows = self.conn.execute(
            """
            SELECT * FROM listings
            WHERE source = ? AND board_id = ? AND status = 'open'
              AND listing_key NOT IN (SELECT k FROM _seen)
            """,
            (source, board_id),
        ).fetchall()
        for row in rows:
            self.conn.execute(
                "UPDATE listings SET status = 'closed', closed_at = ?, last_seen = ? WHERE listing_key = ?",
                (observed_at, observed_at, row["listing_key"]),
            )
            obs = JobObservation(
                source=row["source"],
                board_id=row["board_id"],
                source_job_id=row["source_job_id"],
                company=row["company"],
                title=row["title"],
                apply_url=row["apply_url"],
                location_raw=row["location_raw"] or "",
                city=row["city"] or "",
                region=row["region"] or "",
                country=row["country"] or "",
                remote=None if row["remote"] is None else bool(row["remote"]),
                workplace=row["workplace"] or "",
                department=row["department"] or "",
                posted_at=row["posted_at"] or "",
                sector=row["sector"] or "",
            )
            self._insert_observation(run_id, observed_at, row["listing_key"], row["job_id"], obs, "closed")
        self.conn.execute("DROP TABLE IF EXISTS _seen")
        return rows

    def _record_board(self, run_id: int, result: FetchResult, seen: int) -> None:
        self.conn.execute(
            """
            INSERT INTO run_boards (run_id, source, board_id, success, complete, skipped, jobs_seen, error)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(run_id, source, board_id) DO UPDATE SET
              success=excluded.success,
              complete=excluded.complete,
              skipped=excluded.skipped,
              jobs_seen=excluded.jobs_seen,
              error=excluded.error
            """,
            (
                run_id,
                result.source,
                result.board_id,
                1 if result.success else 0,
                1 if result.complete else 0,
                1 if result.skipped else 0,
                seen,
                result.error[:500] if result.error else "",
            ),
        )

    def _recompute_job(self, job_id: str) -> None:
        rows = self.conn.execute(
            "SELECT * FROM listings WHERE job_id = ? ORDER BY last_seen DESC",
            (job_id,),
        ).fetchall()
        if not rows:
            return
        open_rows = [row for row in rows if row["status"] == "open"]
        active = open_rows or rows
        primary = active[0]
        pay = next((row for row in active if row["pay_min"] is not None or row["pay_max"] is not None), None)
        status = "open" if open_rows else "closed"
        first_seen = min(row["first_seen"] for row in rows)
        last_seen = max(row["last_seen"] for row in rows)
        closed_at = None
        if status == "closed":
            closed_at = max((row["closed_at"] or row["last_seen"]) for row in rows)
        posted_values = [row["posted_at"] for row in rows if row["posted_at"]]
        posted_at = min(posted_values) if posted_values else ""
        sources = sorted({row["source"] for row in active})
        loc = location_key(
            primary["city"] or "",
            primary["region"] or "",
            primary["country"] or "",
            None if primary["remote"] is None else bool(primary["remote"]),
            primary["workplace"] or "",
            primary["location_raw"] or "",
        )
        # Keep the id passed in. Listings already point at it. A changed location
        # key creates a new id at write time; this row is the projection.
        self.conn.execute(
            """
            INSERT INTO jobs (
              job_id, company, company_norm, title, title_norm, location_key,
              location_raw, city, region, country, remote, workplace,
              pay_min, pay_max, pay_currency, pay_period, department, employment_type,
              posted_at, apply_url, sector, sources, first_seen, last_seen, status, closed_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(job_id) DO UPDATE SET
              company=excluded.company,
              company_norm=excluded.company_norm,
              title=excluded.title,
              title_norm=excluded.title_norm,
              location_key=excluded.location_key,
              location_raw=excluded.location_raw,
              city=excluded.city,
              region=excluded.region,
              country=excluded.country,
              remote=excluded.remote,
              workplace=excluded.workplace,
              pay_min=excluded.pay_min,
              pay_max=excluded.pay_max,
              pay_currency=excluded.pay_currency,
              pay_period=excluded.pay_period,
              department=excluded.department,
              employment_type=excluded.employment_type,
              posted_at=excluded.posted_at,
              apply_url=excluded.apply_url,
              sector=excluded.sector,
              sources=excluded.sources,
              first_seen=excluded.first_seen,
              last_seen=excluded.last_seen,
              status=excluded.status,
              closed_at=excluded.closed_at
            """,
            (
                job_id,
                primary["company"],
                norm_company(primary["company"]),
                primary["title"],
                norm_title(primary["title"]),
                loc,
                primary["location_raw"],
                primary["city"],
                primary["region"],
                primary["country"],
                primary["remote"],
                primary["workplace"],
                None if pay is None else pay["pay_min"],
                None if pay is None else pay["pay_max"],
                "" if pay is None else (pay["pay_currency"] or ""),
                "" if pay is None else (pay["pay_period"] or ""),
                primary["department"],
                primary["employment_type"],
                posted_at,
                primary["apply_url"],
                primary["sector"],
                ",".join(sources),
                first_seen,
                last_seen,
                status,
                closed_at,
            ),
        )

    def counts(self) -> dict:
        def one(sql: str) -> int:
            return int(self.conn.execute(sql).fetchone()[0])

        return {
            "open_jobs": one("SELECT COUNT(*) FROM jobs WHERE status = 'open'"),
            "closed_jobs": one("SELECT COUNT(*) FROM jobs WHERE status = 'closed'"),
            "open_postings": one("SELECT COUNT(*) FROM listings WHERE status = 'open'"),
            "closed_postings": one("SELECT COUNT(*) FROM listings WHERE status = 'closed'"),
            "companies": one("SELECT COUNT(DISTINCT company_norm) FROM jobs WHERE status = 'open'"),
            "countries": one(
                "SELECT COUNT(DISTINCT country) FROM jobs WHERE status = 'open' AND country IS NOT NULL AND country != ''"
            ),
            "observations": one("SELECT COUNT(*) FROM observations"),
        }


# Re-exported for tests that want the same id function the store uses.
def listing_job_id(obs: JobObservation) -> str:
    _obs, job_id, _loc = finalize_observation(obs)
    return job_id or job_id_for(obs.company, obs.title, "unspecified")
