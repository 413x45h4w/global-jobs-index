"""Write the static dashboard payload from the current job projection."""

from __future__ import annotations

import json
from pathlib import Path

from jobdir.storage import Store, utc_now


def export_dashboard(store: Store, out_dir: str | Path) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = store.conn.execute(
        """
        SELECT job_id, company, title, location_raw, city, region, country, remote, workplace,
               pay_min, pay_max, pay_currency, pay_period, department, employment_type,
               posted_at, apply_url, sector, sources, first_seen, last_seen, status
        FROM jobs
        WHERE status = 'open'
        ORDER BY posted_at DESC, company, title
        """
    ).fetchall()
    jobs = []
    for row in rows:
        item = {
            "id": row["job_id"],
            "company": row["company"],
            "title": row["title"],
            "location": _location(row),
            "city": row["city"] or "",
            "region": row["region"] or "",
            "country": row["country"] or "",
            "remote": None if row["remote"] is None else bool(row["remote"]),
            "workplace": row["workplace"] or "",
            "pay_min": row["pay_min"],
            "pay_max": row["pay_max"],
            "pay_currency": row["pay_currency"] or "",
            "pay_period": row["pay_period"] or "",
            "department": row["department"] or "",
            "employment_type": row["employment_type"] or "",
            "posted_at": row["posted_at"] or "",
            "apply_url": row["apply_url"],
            "sector": row["sector"] or "",
            "sources": [part for part in (row["sources"] or "").split(",") if part],
            "first_seen": row["first_seen"],
            "last_seen": row["last_seen"],
        }
        jobs.append({key: value for key, value in item.items() if value not in (None, "", [])})

    postings = store.conn.execute(
        """
        SELECT source, COUNT(*) AS n
        FROM listings
        WHERE status = 'open'
        GROUP BY source
        ORDER BY n DESC
        """
    ).fetchall()
    countries = store.conn.execute(
        """
        SELECT country, COUNT(*) AS n
        FROM jobs
        WHERE status = 'open' AND country IS NOT NULL AND country != ''
        GROUP BY country
        ORDER BY n DESC
        LIMIT 30
        """
    ).fetchall()
    sectors = store.conn.execute(
        """
        SELECT COALESCE(NULLIF(sector, ''), 'other') AS sector, COUNT(*) AS n
        FROM jobs
        WHERE status = 'open'
        GROUP BY 1
        ORDER BY n DESC
        """
    ).fetchall()
    notable = {}
    for name in ("Kalshi", "Polymarket"):
        notable[name.lower()] = int(
            store.conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE status = 'open' AND company_norm = ?",
                (name.lower(),),
            ).fetchone()[0]
        )
    base = store.counts()
    stats = {
        "generated_at": utc_now(),
        "open_jobs": base["open_jobs"],
        "closed_jobs": base["closed_jobs"],
        "open_postings": base["open_postings"],
        "closed_postings": base["closed_postings"],
        "companies": base["companies"],
        "countries": base["countries"],
        "observations": base["observations"],
        "with_pay": sum(1 for job in jobs if "pay_min" in job or "pay_max" in job),
        "remote_jobs": sum(1 for job in jobs if job.get("workplace") == "remote" or job.get("remote") is True),
        "postings_by_source": {row["source"]: row["n"] for row in postings},
        "jobs_by_sector": {row["sector"]: row["n"] for row in sectors},
        "top_countries": [{"country": row["country"], "jobs": row["n"]} for row in countries],
        "notable": notable,
    }
    (out / "jobs.json").write_text(json.dumps({"generated_at": stats["generated_at"], "jobs": jobs}, separators=(",", ":")), encoding="utf-8")
    (out / "stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    return stats


def _location(row) -> str:
    if row["location_raw"]:
        return row["location_raw"]
    parts = [row["city"] or "", row["region"] or "", row["country"] or ""]
    return ", ".join(part for part in parts if part)
