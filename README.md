# Global Jobs Index

A public directory of open jobs, built to grow toward every posting on the internet without pretending a single scrape can get there. This version pulls real listings from company applicant-tracking systems, keeps every observation, and publishes a static dashboard.

The index is append-only. A job keeps `first_seen` from the first time a source returned it and `last_seen` from the latest sighting. When a board is fully refreshed and a listing is gone, that listing is marked closed. Each new or changed sighting, and each close or reopen, is written to an immutable Parquet part. Identical daily re-fetches advance `last_seen` and do not copy the payload again, so the scheduled refresh stays under GitHub's file-size limit.

## Coverage in this build

Pulled 2026-11-24 from the full CC0 catalog (11,593 boards with a positive open-role count) plus the verified SmartRecruiters boards. The dashboard headline matches `docs/data/stats.json`.

| | |
|---|---|
| Open jobs (deduped) | 779,021 |
| Open postings | 887,530 |
| Companies | 11,754 |
| Countries | 208 |
| Jobs with a pay range | 27,291 |
| Registry boards | 11,593 |
| Kalshi | 67 open jobs (Greenhouse and Ashby) |
| Polymarket | 33 open jobs (Ashby), with structured USD ranges |

Postings by source:

| Source | Open postings |
|---|---|
| Workday | 593,910 |
| Greenhouse | 138,253 |
| Workable | 53,152 |
| Ashby | 47,778 |
| Recruitee | 17,636 |
| SmartRecruiters | 11,861 |
| Personio | 9,007 |
| Rippling | 8,293 |
| Lever | 7,640 |

About 400 catalog tokens 404'd or returned 403/422 and were not used to close jobs. Workday paging recovered full catalogs where the API allows it (CVS Health 18,616). Some large tenants still stop short: the search wraps or a facet bucket stays above the cap, and the client also stops a single board at 4,000 requests so one employer cannot stall the run. Target returned 2,408, Walmart 19,731, Circle K 8,865. Those boards are marked partial and are not used to close listings that were not returned.

Common Crawl was not re-sampled in this full ATS run. `python3 -m jobdir cc-sample` still extracts `JobPosting` JSON-LD from the latest crawl and will not close jobs that a later sample misses.

Parquet on disk is 182 MB across 24 files. The largest file is 49.3 MB, under GitHub's 100 MB hard limit and under the 50 MB warning. The dashboard shards are about 346 MB combined, each file about 10–13 MB.

![Global Jobs Index dashboard](docs/screenshot.png)

See **Known gaps** for what is deliberately not in this seed.

## Architecture

```mermaid
flowchart LR
  registry["data/boards.yaml"] --> run["python -m jobdir run"]
  catalog["CC0 board catalog"] --> discover["python -m jobdir discover"]
  discover --> registry
  ats["Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee, Workday, Personio, Rippling"] --> run
  cc["Common Crawl JSON-LD sample"] --> run
  usajobs["USAJobs if API key is set"] --> run
  run --> scratch["data/work.sqlite scratch"]
  scratch --> parquet["data/parquet observation parts and projection"]
  scratch --> export["docs/data shards"]
  export --> pages["GitHub Pages dashboard"]
```

Layers:

1. **Registry.** `data/boards.yaml` (and the same rows in `data/boards.csv`) maps a company to a public board id. Workday rows also store host, tenant, and career-site path, which cannot be guessed from a company name.
2. **Adapters.** Each source implements `fetch(board, client) -> FetchResult`. A result is either a complete live-board read, a failed read, a skip, or a snapshot. Only a complete live-board read can mark listings closed.
3. **Normalize.** Company, title, city, region, country, remote/hybrid/on-site, pay range and currency, department, posted date, apply URL, and source.
4. **Dedupe.** A job id is a hash of normalized company + title + location. The same role on Greenhouse and Ashby becomes one job with two listings. Different cities stay separate.
5. **Store.** A gitignored SQLite file (`data/work.sqlite`) is the scratch projection for one run. Durable history is ZSTD Parquet under `data/parquet/`:
   - `observations/source=*/dt=*/part-*.parquet` — append-only. A part is never rewritten. Rows are new listings, payload changes, closes, and reopens, each with `observed_at`.
   - `projection/listings/` and `projection/jobs/` — derived current state, including `first_seen` and `last_seen`. Replaced each publish because it is computed from the scratch database plus the history of changes.
6. **Dashboard.** `docs/` is a static site. It reads `docs/data/stats.json` and the compact open-job shards listed there.

### Data model

| Table | What it keeps |
|---|---|
| `observations` | One Parquet row when a listing is first seen, when its normalized payload changes, and when it is closed or reopened. Parts are insert-only. |
| `listings` | One row per source listing (`source + board + source job id`) with `first_seen`, `last_seen`, `open` or `closed`. |
| `jobs` | Deduplicated projection. Open while any listing is open. |
| `runs` / `run_boards` | When a pull happened and whether each board succeeded. A failed board does not close its jobs. |

Pay is stored only when the source provides a structured range (Ashby compensation, Lever `salaryRange`, SmartRecruiters when present, Recruitee `salary`, USAJobs remuneration) or a short explicit range such as Lever's compensation blurb. Full job-description HTML is not stored.

## Sources

Public, no-login APIs:

| Source | Endpoint | Notes |
|---|---|---|
| Greenhouse | `boards-api.greenhouse.io/v1/boards/{token}/jobs` | One response per board. Pay is often absent from the list payload. |
| Lever | `api.lever.co/v0/postings/{token}` or `api.eu.lever.co` | The seed includes every Lever board in the catalog that had open roles. |
| Ashby | `api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true` | Kalshi, Polymarket, OpenAI, Cursor, Ramp, and others. |
| Workable | `apply.workable.com/api/v1/widget/accounts/{token}` | Widget API. Cloudflare may rate-limit; the client backs off. |
| SmartRecruiters | `api.smartrecruiters.com/v1/companies/{id}/postings` | Paginated. Includes Wise, Bosch Group, ServiceNow, Grab, Palantir. |
| Recruitee | `{token}.recruitee.com/api/offers/` | Full catalog of boards with open roles. |
| Personio | `{token}.jobs.personio.de/xml` | Public XML feed. Descriptions are discarded. |
| Rippling | `api.rippling.com/platform/api/ats/v1/board/{token}/jobs` | Public JSON list. |
| Workday | `POST /wday/cxs/{tenant}/{site}/jobs` | Page size 20. Some tenants paginate the whole catalog. Others wrap to page one after about 2,000 hits even when facet counts are higher. A wrapped board is re-read once per facet value (and one more facet level if a bucket is still capped). A board that is still short of its facet total is not used to mark jobs closed. |
| USAJobs | `data.usajobs.gov/api/search` | Used only when both `USAJOBS_API_KEY` and `USAJOBS_USER_AGENT` are set. Otherwise the run logs a skip and continues. |
| Common Crawl | Latest crawl CDX + WARC byte ranges | Sampled JSON-LD `JobPosting` extraction using URL prefix queries. A bare `*` query 404s on the current index. Snapshot source: absence from a sample does not close jobs. |

Licensed feeds are stubs in `jobdir/sources/licensed.py`:

- Coresignal (`CORESIGNAL_API_KEY`)
- Lightcast (`LIGHTCAST_CLIENT_ID`)
- TheirStack (`THEIRSTACK_API_KEY`)

If a key is missing, the adapter skips. If a key is present, it still skips and says the client is not implemented. Empty licensed pulls never close jobs.

This project does **not** scrape LinkedIn or Indeed.

## Registry and discovery

Rebuild the seed:

```bash
python3 scripts/build_registry.py
```

The registry is the full CC0 catalog of boards that had a positive open-role count on 2026-11-19, for Greenhouse, Ashby, Lever, Workable, Workday, Recruitee, Personio, and Rippling, plus the SmartRecruiters boards verified directly against that API. Curated display names override the catalog slug for trading and crypto companies (Jane Street, DRW, Jump, IMC, Optiver, Virtu, Kalshi, Polymarket, Coinbase, and the rest of the checked set).

`data/discovery/cc0-board-directory.csv` is a CC0 snapshot (2026-11-19) of a public board directory: 12,244 board ids across Greenhouse, Ashby, Workable, Workday, Recruitee, Lever, Personio, and Rippling. Attribution is in `data/discovery/ATTRIBUTION.txt`. Jobs are fetched again from the vendor APIs; listing text is not copied from the catalog.

Find boards that are in the catalog but not in the registry:

```bash
python3 -m jobdir discover
python3 -m jobdir discover --apply   # merges them into data/boards.yaml
```

URL patterns for Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee, and Workday are parsed by `jobdir.discover.parse_board_url`, which is what a Common Crawl URL harvest should call before it verifies a token.

## Common Crawl

A sampled run is `python3 -m jobdir cc-sample --records 40` or `python3 -m jobdir run --with-cc`. It:

1. Reads the newest crawl id from `https://index.commoncrawl.org/collinfo.json`.
2. Queries the CDX index for a few career-site URL patterns, HTML 200s only, with a small limit.
3. Fetches each WARC record with an HTTP `Range` request to `data.commoncrawl.org`.
4. Decompresses the record and reads `application/ld+json` blocks whose `@type` is `JobPosting`.

The full crawl is resumable and is **not** what the daily job does:

```bash
python3 -m jobdir cc-run --pattern 'jobs.lever.co/*'
```

That writes `data/cc/checkpoint.json` with the crawl id, the pattern, and the next CDX page (`showNumPages` on the CDX API). Re-running continues the same checkpoint. A new crawl id stops the command until you pass `--ignore-crawl-change` or delete the checkpoint, so a monthly crawl does not silently mix indexes.

To finish a full extract, walk every pattern you care about (`boards.greenhouse.io/*`, `job-boards.greenhouse.io/*`, `jobs.lever.co/*`, `jobs.eu.lever.co/*`, `jobs.ashbyhq.com/*`, `apply.workable.com/*`, `jobs.smartrecruiters.com/*`, `*.recruitee.com/*`, `*.myworkdayjobs.com/*`), page the CDX API, and call `fetch_warc_html` + `observations_from_html` for each record, committing observations in batches. Checkpoint after every page. Treat the result as a `snapshot` source so a partial page never closes jobs. Expect this to be a separate machine job: the crawl is tens of billions of pages, and only a thin slice is career HTML with JSON-LD.

## Run it

Requirements: Python 3.11+. No third-party packages.

```bash
python3 -m unittest discover -s tests -v
python3 scripts/run_local.sh --resume
# or
python3 -m jobdir run
python3 -m jobdir run --sources ashby --boards kalshi,polymarket
python3 -m jobdir stats
python3 -m jobdir export
```

Outputs:

- `data/parquet/` — append-only observation parts and the derived projection
- `data/work.sqlite` — gitignored scratch database for the run
- `docs/data/stats.json` — headline counts and the list of shard files
- `docs/data/shards/` — compact open jobs, one or more files per source

Serve the dashboard locally:

```bash
python3 -m http.server -d docs 8000
```

Open `http://127.0.0.1:8000`. Filters are reflected in the query string (`?company=Kalshi&workplace=remote`).

USAJobs, when you have a key from the USAJobs developer portal:

```bash
export USAJOBS_API_KEY="..."
export USAJOBS_USER_AGENT="you@example.com"
python3 -m jobdir run --sources usajobs
```

The user-agent must be the email address USAJobs asks for. Without either variable the source is skipped.

### GitHub Actions

- `.github/workflows/test.yml` runs the unit tests.
- `.github/workflows/refresh.yml` runs the ATS pull daily at 06:30 UTC (timeout 330 minutes) and commits `data/parquet` plus `docs/data`. Unchanged listings do not append a second payload, so the commit stays bounded. Optional secrets: `USAJOBS_API_KEY`, `USAJOBS_USER_AGENT`. Resume a local run with `python3 -m jobdir run --resume`.
- `.github/workflows/pages.yml` deploys `docs/` to GitHub Pages. In the repo settings, set Pages to GitHub Actions.

## Dashboard

The page is static HTML, CSS, and one script. It shows total open jobs, companies, countries, and open postings, then postings by source. Search and filters cover company, title, location, workplace, source, sector, and posted date. "Apply" links back to the employer's own board.

## Roadmap to full coverage

1. **Finish the public ATS long tail.** `jobdir discover --apply` already knows the other ~12,000 catalog boards. Pull them in batches by source. Add a per-board checkpoint so a multi-hour run can resume. Personio (`{company}.jobs.personio.de/xml`) and Rippling (`api.rippling.com/platform/api/ats/v1/board/{token}/jobs`) are in the catalog and need adapters; both are public and were left out of this version.
2. **Workday at scale.** The catalog has 1,371 Workday sites and about 547,000 reported openings. The CXS search caps responses (this client stops at 2,000 and refuses to close jobs on a truncated board). Full coverage needs the cap documented per tenant, detail calls for city/country, and a queue that does not mark a board complete until the vendor's own total is reached or the cap is recorded.
3. **Common Crawl as the long tail.** Run `cc-run` across the patterns above on a machine with disk for WARC slices. Keep it resumable. Use it for employers who are not on a known ATS, not as a replacement for the structured APIs.
4. **More structured pay.** Greenhouse often hides compensation in the per-job payload or in HTML. Fetching that only for boards that opt into pay transparency is the next step; do not store full descriptions in `observations`.
5. **USAJobs and other government feeds.** The adapter is done; it needs a key in Actions secrets. Country and regional government APIs can follow the same optional-key pattern.
6. **Licensed feeds.** Implement Coresignal, Lightcast, and TheirStack only under contract. Keep them behind the stub interface so a missing key cannot wipe open jobs.
7. **Deduping and identity.** Today's key is company + title + location. Next: a stable employer id (so "Kalshi" and "Kalshi, Inc." already collapse; subsidiaries still need a human map), multi-location postings exploded into one listing per city, and a closed-job retention policy that compacts old observation payloads without deleting the fact of the sighting.
8. **What stays out.** LinkedIn and Indeed are not scraped. They are not stable public job APIs, and copying them would not be a path to a durable open index.

## Known gaps

- The registry is every catalog board with a positive open-role count (11,593) plus SmartRecruiters. About 400 of those tokens now 404 or 403. Boards with a zero count in the 2026-11-19 catalog were not included.
- Workday still cannot return every opening at every large employer. CVS Health came back in full (18,616). Target stopped at 2,408, Walmart at 19,731, and Circle K at 8,865 because a facet bucket wrapped or the per-board request budget (4,000) was spent. Partial boards are not used to mark unseen listings closed.
- Lever and Recruitee company labels are title-cased board tokens when the API does not return a display name.
- A role posted in two cities is two jobs. A retitled role is a new job; the old one closes on the next full read of that board.
- This full ATS rebuild did not re-sample Common Crawl. `python3 -m jobdir cc-sample` still reads `JobPosting` JSON-LD from the latest crawl using URL prefixes. Wildcard CDX queries 404 or time out. `python3 -m jobdir cc-run` records the page checkpoint for a full resumable walk.
- USAJobs is empty unless you export a key.
- Coresignal, Lightcast, and TheirStack do not fetch anything yet.
- No LinkedIn. No Indeed.
- Observation parts are append-only and small on a quiet day. The projection Parquet is rewritten each publish. If `jobs.parquet` exceeds 80 MB it is split into hash buckets so no file crosses GitHub's 100 MB limit. Git LFS is not used; partitioned Parquet stays in normal git.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The tests cover location parsing, pay text, YAML round-trip, URL-to-board parsing, cross-source dedupe, close and reopen with `first_seen` preserved, failed fetches that must not close jobs, snapshot sources that must not close jobs, and schema.org `JobPosting` JSON-LD.
