"""
Unit tests for src/ingestion/load_api.py: what happens when the CFPB API is
slow or stops answering. No network needed: the API is replaced by a fake,
and the warehouse is a throwaway DuckDB file in a temp folder.

Run from the project folder:
    python -m unittest discover tests
"""

import sys
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "ingestion"))
import load_api  # noqa: E402
import warehouse  # noqa: E402


def fake_page(complaint_ids, total, day="2026-11-05"):
    """One API page in the same shape the real API sends."""
    hits = [{
        "_source": {
            "complaint_id": str(cid),
            "date_received": f"{day}T12:00:00Z",
            "date_sent_to_company": f"{day}T12:00:00Z",
            "product": "Checking or savings account",
            "company": "EXAMPLE BANK",
            "timely": "Yes",
        },
        "sort": [1_000_000 + cid, cid],
    } for cid in complaint_ids]
    return {
        "hits": {"total": {"value": total}, "hits": hits},
        "_meta": {"last_indexed": "2026-11-12T12:00:00+00:00"},
    }


class FetchDayTest(unittest.TestCase):

    def test_pages_until_a_short_page(self):
        pages = [fake_page(range(1, 101), 150), fake_page(range(101, 151), 150)]
        with mock.patch.object(load_api, "get_with_retries", side_effect=pages), \
                mock.patch.object(load_api, "PAUSE_SECONDS", 0):
            records, api_count, _ = load_api.fetch_day(date(2026, 11, 5), mock.Mock())
        self.assertEqual(len(records), 150)
        self.assertEqual(api_count, 150)

    def test_api_failure_becomes_gave_up(self):
        error = requests.exceptions.ReadTimeout("Read timed out")
        with mock.patch.object(load_api, "get_with_retries", side_effect=error):
            with self.assertRaises(load_api.ApiGaveUp):
                load_api.fetch_day(date(2026, 11, 5), mock.Mock())

    def test_passed_deadline_stops_before_asking(self):
        fake_get = mock.Mock()
        with mock.patch.object(load_api, "get_with_retries", fake_get):
            with self.assertRaises(load_api.ApiGaveUp):
                load_api.fetch_day(date(2026, 11, 5), mock.Mock(), deadline=time.monotonic() - 1)
        fake_get.assert_not_called()


class MainStopsCleanlyTest(unittest.TestCase):
    """Day 1 loads, then the API dies: the script must keep day 1 and exit without an error."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        root = Path(self.folder.name)
        self.patches = [
            mock.patch.object(warehouse, "DB_PATH", root / "test.duckdb"),
            mock.patch.object(warehouse, "LOG_PATH", root / "test.log"),
            mock.patch.object(load_api, "PAUSE_SECONDS", 0),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.folder.cleanup()

    def test_keeps_loaded_days_and_logs_skipped_ones(self):
        answers = [fake_page([1, 2, 3], 3), requests.exceptions.ReadTimeout("Read timed out")]
        argv = ["load_api.py", "--start", "2026-11-05", "--end", "2026-11-07"]
        with mock.patch.object(load_api, "get_with_retries", side_effect=answers), \
                mock.patch.object(sys, "argv", argv):
            load_api.main()

        con = warehouse.connect()
        held = con.execute("SELECT count(*) FROM raw.complaints").fetchone()[0]
        notes = [row[0] for row in con.execute("SELECT notes FROM raw.load_log ORDER BY run_id").fetchall()]
        con.close()
        self.assertEqual(held, 3)
        self.assertTrue(any("skipped 2026-11-06 to 2026-11-07" in note for note in notes))


if __name__ == "__main__":
    unittest.main()
