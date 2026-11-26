"""Command line for the public job directory.

Examples:
  python3 -m jobdir run
  python3 -m jobdir run --sources greenhouse,ashby
  python3 -m jobdir discover
  python3 -m jobdir cc-sample --records 40
  python3 -m jobdir export
  python3 -m jobdir stats
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jobdir.discover import catalog_to_boards, load_catalog, missing_boards, parse_board_url
from jobdir.export import export_dashboard
from jobdir.http import Client
from jobdir.models import Board
from jobdir.parquet_export import append_run_manifest, bootstrap_projection, export_parquet, parquet_stats
from jobdir.pipeline import run_pipeline
from jobdir.sources.commoncrawl import CommonCrawlAdapter, cdx_page_count, latest_crawl
from jobdir.storage import Store
from jobdir.yamlreg import dump_boards, load_boards_file

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "work.sqlite"
DEFAULT_REGISTRY = ROOT / "data" / "boards.yaml"
DEFAULT_OUT = ROOT / "docs" / "data"
DEFAULT_CATALOG = ROOT / "data" / "discovery" / "cc0-board-directory.csv"
DEFAULT_PARQUET = ROOT / "data" / "parquet"
CHECKPOINT = ROOT / "data" / "cc" / "checkpoint.json"
BOARD_CHECKPOINT = ROOT / "data" / "checkpoints" / "boards.tsv"


def _boards_from_args(args) -> list[Board]:
    boards = load_boards_file(str(args.registry))
    if args.sources:
        wanted = {item.strip() for item in args.sources.split(",") if item.strip()}
        boards = [board for board in boards if board.source in wanted]
    if getattr(args, "boards", None):
        wanted_ids = {item.strip() for item in args.boards.split(",") if item.strip()}
        boards = [board for board in boards if board.board_id in wanted_ids or board.company in wanted_ids]
    return boards


def _open_store(args) -> Store:
    path = Path(args.db)
    path.parent.mkdir(parents=True, exist_ok=True)
    fresh = not path.exists()
    store = Store(str(path))
    if fresh:
        loaded = bootstrap_projection(store, args.parquet)
        if loaded:
            print(f"loaded {loaded} listings from parquet", flush=True)
    return store


def _publish(store: Store, args, stats: dict | None = None) -> dict:
    parquet_info = export_parquet(store, args.parquet)
    exported = export_dashboard(store, args.out)
    if stats is not None:
        append_run_manifest(args.parquet, {"counts": store.counts(), "parquet": parquet_stats(args.parquet)})
    return {"parquet": parquet_info, "export": exported}


def cmd_run(args) -> int:
    boards = _boards_from_args(args)
    if not boards and not args.with_cc:
        print("No boards selected", file=sys.stderr)
        return 2
    store = _open_store(args)
    try:
        def _flush(done_boards: int) -> None:
            info = export_parquet(store, args.parquet)
            print(f"flush after {done_boards} boards bytes={info['bytes']}", flush=True)

        stats = run_pipeline(
            store,
            boards,
            include_commoncrawl=args.with_cc,
            cc_records=args.cc_records,
            checkpoint=args.checkpoint,
            resume=args.resume,
            on_batch=_flush,
            batch_size=args.flush_every,
        )
        published = _publish(store, args, stats)
        store.vacuum()
    finally:
        store.close()
    summary = {
        "open_jobs": published["export"]["open_jobs"],
        "companies": published["export"]["companies"],
        "countries": published["export"]["countries"],
        "notable": published["export"]["notable"],
        "postings_by_source": published["export"]["postings_by_source"],
        "parquet_bytes": published["parquet"]["bytes"],
    }
    print(json.dumps(summary, indent=2))
    return 0


def cmd_export(args) -> int:
    store = _open_store(args)
    try:
        published = _publish(store, args, None)
    finally:
        store.close()
    print(json.dumps({"open_jobs": published["export"]["open_jobs"], "parquet_bytes": published["parquet"]["bytes"]}, indent=2))
    return 0


def cmd_stats(args) -> int:
    store = Store(str(args.db))
    try:
        print(json.dumps(store.counts(), indent=2))
    finally:
        store.close()
    return 0


def cmd_discover(args) -> int:
    rows = load_catalog(str(args.catalog))
    catalog = catalog_to_boards(rows)
    existing = load_boards_file(str(args.registry)) if Path(args.registry).exists() else []
    missing = missing_boards(catalog, existing)
    print(f"catalog boards with open roles: {len(catalog)}")
    print(f"already in registry: {len(existing)}")
    print(f"not in registry: {len(missing)}")
    by_source: dict[str, int] = {}
    for board in missing:
        by_source[board.source] = by_source.get(board.source, 0) + 1
    print("missing by source:", json.dumps(by_source))
    if args.urls:
        for line in Path(args.urls).read_text(encoding="utf-8").splitlines():
            parsed = parse_board_url(line.strip())
            if parsed:
                print(f"url {parsed.source} {parsed.board_id} {parsed.workday_site}")
    if args.apply:
        merged = existing + missing
        # Stable, unique.
        seen = set()
        ordered = []
        for board in merged:
            if board.key in seen or not board.board_id:
                continue
            seen.add(board.key)
            ordered.append(board)
        Path(args.registry).write_text(dump_boards(ordered), encoding="utf-8")
        print(f"wrote {len(ordered)} boards to {args.registry}")
    else:
        for board in missing[: args.limit]:
            print(f"{board.source:16} {board.board_id}")
    return 0


def cmd_cc_sample(args) -> int:
    client = Client()
    adapter = CommonCrawlAdapter(records=args.records)
    result = adapter.fetch(Board("Common Crawl", "commoncrawl", "commoncrawl"), client)
    print(result.error or "no note")
    print(f"success={result.success} jobs={len(result.observations)}")
    for obs in result.observations[:20]:
        print(f"- {obs.company} | {obs.title} | {obs.location_raw} | {obs.apply_url}")
    if args.write and result.observations:
        store = Store(str(args.db))
        try:
            run_id = store.start_run()
            summary = store.apply(run_id, result)
            store.finish_run(run_id, summary)
            export_dashboard(store, args.out)
        finally:
            store.close()
    return 0 if result.success else 1


def cmd_cc_run(args) -> int:
    """Resumable CDX page walk. Records pages in data/cc/checkpoint.json.

    This does not download every WARC by default. Pass --fetch to pull each
    page's records (still bounded by --limit per invocation).
    """
    client = Client()
    crawl_id, cdx = latest_crawl(client)
    checkpoint_path = Path(args.checkpoint)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    if checkpoint_path.exists():
        state = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    else:
        state = {"crawl_id": crawl_id, "patterns": {}}
    if state.get("crawl_id") != crawl_id and not args.ignore_crawl_change:
        print(f"checkpoint crawl {state.get('crawl_id')} != latest {crawl_id}. Pass --ignore-crawl-change to continue.")
        return 2
    pattern = args.pattern
    pattern_state = state["patterns"].setdefault(pattern, {"next_page": 0, "pages": None, "records": 0, "done": False})
    if pattern_state.get("pages") is None:
        pattern_state["pages"] = cdx_page_count(client, cdx, pattern)
        print(f"{pattern} pages={pattern_state['pages']}")
    print(json.dumps({"crawl_id": crawl_id, "pattern": pattern, **pattern_state}, indent=2))
    checkpoint_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(f"checkpoint written to {checkpoint_path}")
    print("Full extraction is resumable: rerun the same command. Fetching WARC bytes is `cc-sample`.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobdir", description="Public job directory")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--parquet", default=str(DEFAULT_PARQUET))
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="Fetch registry boards and export the dashboard")
    run.add_argument("--sources", default="", help="Comma-separated source names")
    run.add_argument("--boards", default="", help="Comma-separated board ids or company names")
    run.add_argument("--with-cc", action="store_true", help="Also sample Common Crawl JSON-LD")
    run.add_argument("--cc-records", type=int, default=12)
    run.add_argument("--resume", action="store_true", help="Skip boards already recorded in the checkpoint")
    run.add_argument("--checkpoint", default=str(BOARD_CHECKPOINT))
    run.add_argument("--flush-every", type=int, default=1000)
    run.set_defaults(func=cmd_run)

    export = sub.add_parser("export", help="Rebuild docs/data from the database")
    export.set_defaults(func=cmd_export)

    stats = sub.add_parser("stats", help="Print store counts")
    stats.set_defaults(func=cmd_stats)

    discover = sub.add_parser("discover", help="Diff the board catalog against the registry")
    discover.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    discover.add_argument("--limit", type=int, default=40)
    discover.add_argument("--apply", action="store_true", help="Merge missing catalog boards into the registry")
    discover.add_argument("--urls", default="", help="Optional file of URLs to parse")
    discover.set_defaults(func=cmd_discover)

    sample = sub.add_parser("cc-sample", help="Sample JobPosting JSON-LD from the latest crawl")
    sample.add_argument("--records", type=int, default=30)
    sample.add_argument("--write", action="store_true")
    sample.set_defaults(func=cmd_cc_sample)

    full = sub.add_parser("cc-run", help="Advance the resumable Common Crawl checkpoint")
    full.add_argument("--pattern", default="jobs.ashbyhq.com/kalshi")
    full.add_argument("--checkpoint", default=str(CHECKPOINT))
    full.add_argument("--ignore-crawl-change", action="store_true")
    full.set_defaults(func=cmd_cc_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
