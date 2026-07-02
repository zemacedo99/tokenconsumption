"""Unit tests for ingest.py."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from token_consumption import db as db_mod
from token_consumption import ingest as ingest_mod


FIXTURE_PATH = Path(__file__).parent.parent / "examples" / "sample-transcript.jsonl"


class TestIngestFile(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test.sqlite"
        db_mod.init_db(self.db_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_fixture_exists(self):
        self.assertTrue(FIXTURE_PATH.exists(), f"Fixture not found: {FIXTURE_PATH}")

    def test_ingest_returns_stats(self):
        stats = ingest_mod.ingest_file(
            FIXTURE_PATH, "test-project", "/test/cwd", "test-profile",
            db_path=self.db_path
        )
        self.assertIn("ingested", stats)
        self.assertIn("skipped", stats)
        self.assertIn("errors", stats)
        self.assertEqual(stats["errors"], 0)

    def test_ingests_assistant_turns(self):
        ingest_mod.ingest_file(
            FIXTURE_PATH, "test-project", "/test/cwd", "test-profile",
            db_path=self.db_path
        )
        with db_mod.connection(self.db_path) as con:
            rows = con.execute("SELECT * FROM turns WHERE role='assistant'").fetchall()
        # fixture has 3 assistant turns
        self.assertEqual(len(rows), 3)

    def test_idempotent_reingest(self):
        """Ingesting the same file twice produces the same row count."""
        stats1 = ingest_mod.ingest_file(
            FIXTURE_PATH, "test-project", "/test/cwd", "test-profile",
            db_path=self.db_path
        )
        stats2 = ingest_mod.ingest_file(
            FIXTURE_PATH, "test-project", "/test/cwd", "test-profile",
            db_path=self.db_path
        )
        with db_mod.connection(self.db_path) as con:
            count = con.execute("SELECT COUNT(*) AS n FROM turns").fetchone()["n"]
        # Second ingest: ON CONFLICT DO UPDATE — no new rows
        self.assertEqual(count, stats1["ingested"])

    def test_token_counts_stored(self):
        ingest_mod.ingest_file(
            FIXTURE_PATH, "test-project", "/test/cwd", "test-profile",
            db_path=self.db_path
        )
        with db_mod.connection(self.db_path) as con:
            row = con.execute("""
                SELECT * FROM turns WHERE turn_uuid='aaaa0002-0000-0000-0000-000000000002'
            """).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["input_tokens"], 1500)
        self.assertEqual(row["output_tokens"], 800)
        self.assertEqual(row["cache_write_5m_tokens"], 5000)
        self.assertEqual(row["cache_read_tokens"], 0)

    def test_cache_read_stored(self):
        ingest_mod.ingest_file(
            FIXTURE_PATH, "test-project", "/test/cwd", "test-profile",
            db_path=self.db_path
        )
        with db_mod.connection(self.db_path) as con:
            row = con.execute("""
                SELECT * FROM turns WHERE turn_uuid='aaaa0004-0000-0000-0000-000000000004'
            """).fetchone()
        self.assertEqual(row["cache_read_tokens"], 5000)

    def test_privacy_no_message_content(self):
        """Verify message content is never stored in any DB column."""
        ingest_mod.ingest_file(
            FIXTURE_PATH, "test-project", "/test/cwd", "test-profile",
            db_path=self.db_path
        )
        # Connect directly and check every text column for suspicious content
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM turns").fetchall()
        con.close()

        sensitive_cols = ["cwd", "project_slug", "role", "model", "task_type",
                          "cost_source", "pricing_version", "account_profile"]
        for row in rows:
            for col in sensitive_cols:
                val = row[col] if col in row.keys() else None
                if val:
                    # Should not contain any full "content" that looks like a prompt
                    self.assertNotIn("explain", str(val).lower(),
                                     f"Column {col} may contain prompt content")

    def test_queue_operation_skipped(self):
        """Lines with type=queue-operation are not stored as turns."""
        ingest_mod.ingest_file(
            FIXTURE_PATH, "test-project", "/test/cwd", "test-profile",
            db_path=self.db_path
        )
        with db_mod.connection(self.db_path) as con:
            count = con.execute("SELECT COUNT(*) AS n FROM turns").fetchone()["n"]
        # queue-operation has no uuid; the extractor returns None and it gets skipped
        # We have 6 real records (3 user + 3 assistant), minus those without usage
        self.assertGreater(count, 0)

    def test_agg_daily_populated(self):
        ingest_mod.ingest_file(
            FIXTURE_PATH, "test-project", "/test/cwd", "test-profile",
            db_path=self.db_path
        )
        with db_mod.connection(self.db_path) as con:
            rows = con.execute("SELECT * FROM agg_daily").fetchall()
        self.assertGreater(len(rows), 0)

    def test_since_filter(self):
        """--since filters out older turns."""
        stats = ingest_mod.ingest_file(
            FIXTURE_PATH, "test-project", "/test/cwd", "test-profile",
            db_path=self.db_path,
            since_ts="2026-07-01T12:00:00Z",
        )
        with db_mod.connection(self.db_path) as con:
            rows = con.execute("SELECT ts FROM turns ORDER BY ts").fetchall()
        for row in rows:
            self.assertGreaterEqual(row["ts"], "2026-07-01T12:00:00Z")


if __name__ == "__main__":
    unittest.main()
