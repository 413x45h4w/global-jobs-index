"""Fetch boards and fold them into the append-only store."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from jobdir.http import Client
from jobdir.models import Board, FetchResult
from jobdir.sources import ADAPTERS
from jobdir.storage import Store, utc_now

SOURCE_LIMITS = {
    "greenhouse": 8,
    "ashby": 8,
    "lever": 6,
    "workable": 2,
    "smartrecruiters": 3,
    "recruitee": 4,
    "personio": 4,
    "rippling": 4,
    "workday": 8,
    "usajobs": 1,
    "commoncrawl": 1,
}


def run_pipeline(
    store: Store,
    boards: list[Board],
    *,
    sources: set[str] | None = None,
    include_commoncrawl: bool = False,
    cc_records: int = 30,
    client: Client | None = None,
    checkpoint: str | None = None,
    resume: bool = False,
    on_batch=None,
    batch_size: int = 1000,
) -> dict:
    client = client or Client()
    selected = [board for board in boards if sources is None or board.source in sources]
    if include_commoncrawl and (sources is None or "commoncrawl" in sources):
        if not any(board.source == "commoncrawl" for board in selected):
            selected.append(
                Board(company="Common Crawl", source="commoncrawl", board_id="commoncrawl", sector="other")
            )
    done: set[str] = set()
    checkpoint_path = Path(checkpoint) if checkpoint else None
    if resume and checkpoint_path and checkpoint_path.exists():
        done = {line.strip() for line in checkpoint_path.read_text(encoding="utf-8").splitlines() if line.strip()}
        selected = [board for board in selected if _board_key(board) not in done]
        print(f"resume: skipping {len(done)} finished boards, {len(selected)} left", flush=True)
    if checkpoint_path:
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    run_id = store.start_run()
    observed_at = utc_now()
    semaphores = {name: threading.Semaphore(limit) for name, limit in SOURCE_LIMITS.items()}
    default_sem = threading.Semaphore(4)
    summaries = []
    lock = threading.Lock()

    def _fetch(board: Board) -> FetchResult:
        adapter = ADAPTERS.get(board.source)
        if adapter is None:
            return FetchResult(
                source=board.source,
                board_id=board.board_id,
                success=False,
                complete=False,
                error=f"no adapter for {board.source}",
            )
        if board.source == "commoncrawl":
            adapter.records = cc_records
        sem = semaphores.get(board.source, default_sem)
        with sem:
            return adapter.fetch(board, client)

    workers = min(12, max(1, len(selected)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fetch, board): board for board in selected}
        for future in as_completed(futures):
            board = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001
                result = FetchResult(
                    source=board.source,
                    board_id=board.board_id,
                    success=False,
                    complete=False,
                    error=f"{type(exc).__name__}: {exc}",
                )
            summary = store.apply(run_id, result, observed_at=observed_at)
            summaries.append(summary)
            state = "skip" if result.skipped else ("ok" if result.success else "FAIL")
            print(
                f"{state:4} {len(summaries):5}/{len(selected):<5} {board.source:16} {board.board_id[:40]:40} "
                f"seen={summary['seen']:5} closed={summary['closed']:4} {summary['error'][:120]}",
                flush=True,
            )
            if result.success and checkpoint_path:
                with lock:
                    with checkpoint_path.open("a", encoding="utf-8") as handle:
                        handle.write(_board_key(board) + "\n")
            if on_batch and batch_size and len(summaries) % batch_size == 0:
                on_batch(len(summaries))

    stats = store.counts()
    stats["boards_total"] = len(selected)
    stats["boards_ok"] = sum(1 for item in summaries if item["success"])
    stats["boards_failed"] = sum(1 for item in summaries if not item["success"])
    stats["errors"] = [
        {"source": item["source"], "board_id": item["board_id"], "error": item["error"]}
        for item in summaries
        if item["error"] and not item["success"]
    ]
    store.finish_run(run_id, stats)
    return stats


def _board_key(board: Board) -> str:
    return f"{board.source}\t{board.board_id}"
