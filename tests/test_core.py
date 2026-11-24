"""Unit tests for normalize, registry IO, dedupe, and close detection."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jobdir.discover import parse_board_url
from jobdir.models import Board, FetchResult, JobObservation
from jobdir.normalize import interpret_location, job_id_for, norm_company, parse_pay_text
from jobdir.sources.jsonld import observations_from_html
from jobdir.storage import Store
from jobdir.yamlreg import dump_boards, load_boards


def obs(**kwargs) -> JobObservation:
    base = dict(
        source="greenhouse",
        board_id="demo",
        source_job_id="1",
        company="Kalshi",
        title="Site Reliability Engineer",
        apply_url="https://example.com/jobs/1",
        location_raw="New York, NY",
        sector="markets",
    )
    base.update(kwargs)
    return JobObservation(**base)


class NormalizeTests(unittest.TestCase):
    def test_company_suffix(self):
        self.assertEqual(norm_company("Chime Financial, Inc."), "chime financial")
        self.assertEqual(norm_company("Five Rings LLC"), "five rings")

    def test_us_city_not_confused_with_country_code(self):
        city, region, country, remote, workplace = interpret_location("Chicago, IL")
        self.assertEqual(city, "Chicago")
        self.assertEqual(country, "United States")
        self.assertEqual(region, "Illinois")
        self.assertNotEqual(country, "Israel")
        self.assertIsNone(remote)
        self.assertEqual(workplace, "")

    def test_remote_country(self):
        city, _region, country, remote, workplace = interpret_location("Remote - United States")
        self.assertEqual(city, "")
        self.assertEqual(country, "United States")
        self.assertTrue(remote)
        self.assertEqual(workplace, "remote")

    def test_same_job_id_for_equivalent_locations(self):
        left = interpret_location("New York, NY")
        right = interpret_location("New York, NY, United States")
        key_l = f"{left[0].lower()}|{left[2].lower()}"
        key_r = f"{right[0].lower()}|{right[2].lower()}"
        self.assertEqual(left[0], right[0])
        self.assertEqual(left[2], right[2])
        self.assertEqual(
            job_id_for("Kalshi Inc", "Site Reliability Engineer", key_l),
            job_id_for("Kalshi", "Site Reliability Engineer", key_r),
        )

    def test_pay_text(self):
        low, high, currency, period = parse_pay_text(
            "The United States base range for this position is $87,069-$124,385 plus equity."
        )
        self.assertEqual(low, 87069)
        self.assertEqual(high, 124385)
        self.assertEqual(currency, "USD")
        self.assertEqual(period, "year")


class RegistryTests(unittest.TestCase):
    def test_roundtrip(self):
        boards = [
            Board(
                company='DRW "Engineering"',
                source="greenhouse",
                board_id="drweng",
                sector="trading",
                careers_url="https://job-boards.greenhouse.io/drweng",
            )
        ]
        loaded = load_boards(dump_boards(boards))
        self.assertEqual(loaded[0].company, 'DRW "Engineering"')
        self.assertEqual(loaded[0].board_id, "drweng")

    def test_urls(self):
        self.assertEqual(parse_board_url("https://jobs.ashbyhq.com/kalshi").board_id, "kalshi")
        self.assertEqual(parse_board_url("https://api.eu.lever.co/v0/postings/aave?mode=json").api_base, "https://api.eu.lever.co")
        wd = parse_board_url("https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs")
        self.assertEqual(wd.workday_site, "NVIDIAExternalCareerSite")
        self.assertEqual(wd.workday_tenant, "nvidia")
        self.assertIsNone(parse_board_url("https://apply.workable.com/api/v1/widget/accounts/x"))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.tmp.name) / "jobs.sqlite"))
        self.run_id = self.store.start_run()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_dedupe_and_close_and_reopen(self):
        first = FetchResult(
            source="ashby",
            board_id="kalshi",
            success=True,
            complete=True,
            observations=[
                obs(source="ashby", board_id="kalshi", source_job_id="a", company="Kalshi"),
                obs(
                    source="ashby",
                    board_id="kalshi",
                    source_job_id="b",
                    company="Kalshi",
                    title="Data Scientist",
                    apply_url="https://example.com/jobs/b",
                ),
            ],
        )
        other = FetchResult(
            source="greenhouse",
            board_id="kalshi",
            success=True,
            complete=True,
            observations=[
                obs(
                    source="greenhouse",
                    board_id="kalshi",
                    source_job_id="99",
                    company="Kalshi, Inc.",
                    location_raw="New York, NY, United States",
                )
            ],
        )
        self.store.apply(self.run_id, first, observed_at="2026-11-01T00:00:00+00:00")
        self.store.apply(self.run_id, other, observed_at="2026-11-01T00:00:00+00:00")
        counts = self.store.counts()
        self.assertEqual(counts["open_jobs"], 2)
        self.assertEqual(counts["open_postings"], 3)
        row = self.store.conn.execute(
            "SELECT sources, first_seen FROM jobs WHERE title = ?",
            ("Site Reliability Engineer",),
        ).fetchone()
        self.assertEqual(row["sources"], "ashby,greenhouse")
        self.assertEqual(row["first_seen"], "2026-11-01T00:00:00+00:00")

        # Second run: the data scientist disappeared. The SRE remains.
        second = FetchResult(
            source="ashby",
            board_id="kalshi",
            success=True,
            complete=True,
            observations=[obs(source="ashby", board_id="kalshi", source_job_id="a", company="Kalshi")],
        )
        summary = self.store.apply(self.run_id, second, observed_at="2026-11-02T00:00:00+00:00")
        self.assertEqual(summary["closed"], 1)
        closed = self.store.conn.execute(
            "SELECT status, first_seen FROM jobs WHERE title = ?",
            ("Data Scientist",),
        ).fetchone()
        self.assertEqual(closed["status"], "closed")
        self.assertEqual(closed["first_seen"], "2026-11-01T00:00:00+00:00")
        observations = self.store.conn.execute("SELECT event FROM observations ORDER BY id").fetchall()
        self.assertIn("closed", [item["event"] for item in observations])
        self.assertGreater(len(observations), 3)

        # A failed pull must not close the SRE posting.
        failed = FetchResult(source="ashby", board_id="kalshi", success=False, complete=False, error="timeout")
        self.store.apply(self.run_id, failed, observed_at="2026-11-03T00:00:00+00:00")
        still = self.store.conn.execute(
            "SELECT status FROM listings WHERE source = 'ashby' AND source_job_id = 'a'"
        ).fetchone()
        self.assertEqual(still["status"], "open")

        # Snapshot sources are not closed when absent from a later sample.
        snap = FetchResult(
            source="commoncrawl",
            board_id="commoncrawl",
            success=True,
            complete=False,
            kind="snapshot",
            observations=[
                obs(
                    source="commoncrawl",
                    board_id="commoncrawl",
                    source_job_id="cc1",
                    company="Example",
                    title="Analyst",
                    apply_url="https://example.com/a",
                    location_raw="Austin, TX",
                )
            ],
        )
        self.store.apply(self.run_id, snap, observed_at="2026-11-04T00:00:00+00:00")
        empty = FetchResult(
            source="commoncrawl",
            board_id="commoncrawl",
            success=True,
            complete=True,
            kind="snapshot",
            observations=[],
        )
        self.store.apply(self.run_id, empty, observed_at="2026-11-05T00:00:00+00:00")
        cc = self.store.conn.execute("SELECT status FROM listings WHERE source = 'commoncrawl'").fetchone()
        self.assertEqual(cc["status"], "open")

        # Reopen keeps the original first_seen and appends another observation.
        reopen = FetchResult(
            source="ashby",
            board_id="kalshi",
            success=True,
            complete=True,
            observations=[
                obs(source="ashby", board_id="kalshi", source_job_id="a", company="Kalshi"),
                obs(
                    source="ashby",
                    board_id="kalshi",
                    source_job_id="b",
                    company="Kalshi",
                    title="Data Scientist",
                    apply_url="https://example.com/jobs/b",
                ),
            ],
        )
        before = self.store.counts()["observations"]
        self.store.apply(self.run_id, reopen, observed_at="2026-11-06T00:00:00+00:00")
        revived = self.store.conn.execute(
            "SELECT status, first_seen FROM jobs WHERE title = ?",
            ("Data Scientist",),
        ).fetchone()
        self.assertEqual(revived["status"], "open")
        self.assertEqual(revived["first_seen"], "2026-11-01T00:00:00+00:00")
        self.assertGreater(self.store.counts()["observations"], before)


class JsonLdTests(unittest.TestCase):
    def test_graph(self):
        html = Path(__file__).parent.joinpath("fixtures", "jobposting.html").read_text(encoding="utf-8")
        found = observations_from_html(html, "https://example.com/jobs/1")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].company, "Example Markets")
        self.assertEqual(found[0].title, "Quant Researcher")
        self.assertEqual(found[0].city, "New York")
        self.assertEqual(found[0].pay_min, 200000)
        self.assertEqual(found[0].pay_currency, "USD")
        self.assertTrue(found[0].remote)


if __name__ == "__main__":
    unittest.main()
