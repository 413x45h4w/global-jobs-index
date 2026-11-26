"""Append-only Parquet history plus a rewritten projection.

Observation files are only created, never modified. The projection (current
listing and job rows, including first_seen and last_seen) is derived and may
be replaced. Unchanged re-fetches update last_seen on the projection and do
not append another copy of the same payload, so a daily refresh stays inside
GitHub's file-size limit.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from jobdir.storage import Store

OBSERVATION_SQL = """
SELECT
  id,
  run_id,
  observed_at,
  listing_key,
  job_id,
  source,
  board_id,
  event,
  json_extract(payload_json, '$.company') AS company,
  json_extract(payload_json, '$.title') AS title,
  json_extract(payload_json, '$.location_raw') AS location_raw,
  json_extract(payload_json, '$.city') AS city,
  json_extract(payload_json, '$.region') AS region,
  json_extract(payload_json, '$.country') AS country,
  json_extract(payload_json, '$.remote') AS remote,
  json_extract(payload_json, '$.workplace') AS workplace,
  json_extract(payload_json, '$.pay_min') AS pay_min,
  json_extract(payload_json, '$.pay_max') AS pay_max,
  json_extract(payload_json, '$.pay_currency') AS pay_currency,
  json_extract(payload_json, '$.pay_period') AS pay_period,
  json_extract(payload_json, '$.department') AS department,
  json_extract(payload_json, '$.employment_type') AS employment_type,
  json_extract(payload_json, '$.posted_at') AS posted_at,
  json_extract(payload_json, '$.apply_url') AS apply_url,
  json_extract(payload_json, '$.sector') AS sector,
  json_extract(payload_json, '$.source_job_id') AS source_job_id
FROM src.observations
WHERE id > {since_id}
"""

LISTING_COLUMNS = (
    "listing_key, source, board_id, source_job_id, job_id, company, title, "
    "location_raw, city, region, country, remote, workplace, pay_min, pay_max, "
    "pay_currency, pay_period, department, employment_type, posted_at, apply_url, "
    "sector, first_seen, last_seen, status, closed_at"
)

JOB_COLUMNS = (
    "job_id, company, company_norm, title, title_norm, location_key, location_raw, "
    "city, region, country, remote, workplace, pay_min, pay_max, pay_currency, "
    "pay_period, department, employment_type, posted_at, apply_url, sector, sources, "
    "first_seen, last_seen, status, closed_at"
)


def _since(store: Store) -> int:
    row = store.conn.execute("SELECT v FROM export_state WHERE k = 'observation_id'").fetchone()
    return int(row["v"]) if row else 0


def _set_since(store: Store, value: int) -> None:
    store.conn.execute(
        "INSERT INTO export_state (k, v) VALUES ('observation_id', ?) "
        "ON CONFLICT(k) DO UPDATE SET v = excluded.v",
        (str(value),),
    )
    store.conn.commit()


def export_parquet(store: Store, root: str | Path) -> dict:
    """Write new observation parts and replace the derived projection."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    since = _since(store)
    max_id = store.conn.execute("SELECT COALESCE(MAX(id), 0) FROM observations").fetchone()[0]
    written = []
    con = duckdb.connect()
    con.execute(f"ATTACH '{store.path}' AS src (TYPE SQLITE)")
    if max_id and int(max_id) > since:
        sources = [
            row[0]
            for row in con.execute(
                f"SELECT DISTINCT source FROM src.observations WHERE id > {int(since)} AND source IS NOT NULL"
            ).fetchall()
        ]
        dates = [
            (row[0] or "unknown")[:10]
            for row in con.execute(
                f"SELECT DISTINCT substr(observed_at, 1, 10) FROM src.observations WHERE id > {int(since)}"
            ).fetchall()
        ]
        for source in sources:
            if not _safe(source):
                continue
            for day in dates or ["unknown"]:
                if not _safe(day.replace("-", "")):
                    day = "unknown"
                dest_dir = root / "observations" / f"source={source}" / f"dt={day}"
                dest_dir.mkdir(parents=True, exist_ok=True)
                part = dest_dir / f"part-{int(since)+1:09d}.parquet"
                con.execute(
                    f"""
                    COPY (
                      SELECT * FROM (
                        {OBSERVATION_SQL.format(since_id=int(since))}
                      ) obs
                      WHERE source = '{source}' AND substr(observed_at, 1, 10) = '{day}'
                    ) TO '{part.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
                    """
                )
                if part.exists() and part.stat().st_size > 0:
                    written.append(str(part))
                elif part.exists():
                    part.unlink()
        _set_since(store, int(max_id))
    _write_projection(con, root)
    con.close()
    return {"observation_parts": written, "root": str(root), "bytes": _tree_bytes(root)}


def _write_projection(con, root: Path) -> None:
    listings_root = root / "projection" / "listings"
    jobs_root = root / "projection" / "jobs"
    for directory in (listings_root, jobs_root):
        if directory.exists():
            for child in directory.rglob("*"):
                if child.is_file():
                    child.unlink()
    listings_root.mkdir(parents=True, exist_ok=True)
    jobs_root.mkdir(parents=True, exist_ok=True)
    sources = [row[0] for row in con.execute("SELECT DISTINCT source FROM src.listings").fetchall()]
    for source in sources:
        if not source or not _safe(source):
            continue
        dest = listings_root / f"source={source}" / "listings.parquet"
        dest.parent.mkdir(parents=True, exist_ok=True)
        con.execute(
            f"""
            COPY (
              SELECT {LISTING_COLUMNS} FROM src.listings WHERE source = '{source}'
            ) TO '{dest.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
            """
        )
    jobs_path = jobs_root / "jobs.parquet"
    con.execute(
        f"""
        COPY (SELECT {JOB_COLUMNS} FROM src.jobs)
        TO '{jobs_path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    _split_if_huge(jobs_path, jobs_root)


def _split_if_huge(path: Path, directory: Path) -> None:
    if not path.exists() or path.stat().st_size < 80_000_000:
        return
    con = duckdb.connect()
    # Eight hash buckets keep each piece under the GitHub file cap.
    for bucket in range(8):
        dest = directory / f"jobs-{bucket}.parquet"
        con.execute(
            f"""
            COPY (
              SELECT * FROM read_parquet('{path.as_posix()}')
              WHERE (hash(job_id) % 8 + 8) % 8 = {bucket}
            ) TO '{dest.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
            """
        )
    path.unlink()
    con.close()


def bootstrap_projection(store: Store, root: str | Path) -> int:
    """Load the derived projection into an empty SQLite database."""
    root = Path(root)
    existing = store.conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    if existing:
        return 0
    listing_files = sorted((root / "projection" / "listings").rglob("*.parquet")) if (root / "projection" / "listings").exists() else []
    job_files = sorted((root / "projection" / "jobs").rglob("*.parquet")) if (root / "projection" / "jobs").exists() else []
    if not listing_files and not job_files:
        return 0
    con = duckdb.connect()
    con.execute(f"ATTACH '{store.path}' AS dst (TYPE SQLITE)")
    if listing_files:
        files = _file_list(listing_files)
        con.execute(
            f"""
            INSERT INTO dst.listings ({LISTING_COLUMNS})
            SELECT {LISTING_COLUMNS} FROM read_parquet([{files}])
            """
        )
    if job_files:
        files = _file_list(job_files)
        con.execute(
            f"""
            INSERT INTO dst.jobs ({JOB_COLUMNS})
            SELECT {JOB_COLUMNS} FROM read_parquet([{files}])
            """
        )
    con.close()
    store.conn.commit()
    return int(store.conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0])


def _file_list(paths: list[Path]) -> str:
    return ", ".join("'" + path.as_posix().replace("'", "") + "'" for path in paths)


def _safe(token: str) -> bool:
    return bool(token) and all(ch.isalnum() or ch in "-_" for ch in token)


def _tree_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*.parquet"))


def parquet_stats(root: str | Path) -> dict:
    root = Path(root)
    files = list(root.rglob("*.parquet"))
    largest = max(files, key=lambda path: path.stat().st_size) if files else None
    return {
        "files": len(files),
        "bytes": sum(path.stat().st_size for path in files),
        "largest": None
        if largest is None
        else {"path": str(largest), "bytes": largest.stat().st_size},
    }


def append_run_manifest(root: str | Path, stats: dict) -> None:
    path = Path(root) / "runs.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(stats, default=str) + "\n")
