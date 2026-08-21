"""
Tests for account data integration:
  - schema migration (account_usage_reports, account_balance_snapshots, data_sources)
  - manual CSV/JSON import
  - official API connector error handling (mocked — no real network calls)
  - no secret leakage
  - reconciliation math
"""

import io
import json
import sqlite3
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from token_consumption import db as db_mod
from token_consumption import account as account_mod
from token_consumption.connectors import manual_import
from token_consumption.connectors import anthropic_account


class TestSchemaMigration(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "m.sqlite"

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_fresh_db_has_new_tables(self):
        db_mod.init_db(self.db_path)
        with db_mod.connection(self.db_path) as con:
            tables = {r["name"] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        for t in ("account_usage_reports", "account_balance_snapshots", "data_sources"):
            self.assertIn(t, tables)

    def test_migration_idempotent(self):
        db_mod.init_db(self.db_path)
        db_mod.init_db(self.db_path)  # run twice — must not error
        with db_mod.connection(self.db_path) as con:
            v = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        self.assertEqual(int(v["value"]), db_mod.SCHEMA_VERSION)

    def test_existing_v1_db_migrates_to_current(self):
        """
        Simulate a pre-existing v1 database: the real v1 DDL (turns/estimates/
        agg_daily/meta — unchanged since v1) with schema_version=1, but none
        of the later account/provider/account tables yet. init_db() must walk
        it forward to the current SCHEMA_VERSION, gaining every table added
        since (v2's account tables, v3's providers/accounts hub tables).
        """
        v1_ddl = db_mod.DDL.split("-- ── account_usage_reports")[0]
        con = sqlite3.connect(self.db_path)
        con.executescript(v1_ddl)
        con.execute("INSERT INTO meta VALUES ('schema_version', '1')")
        con.commit()
        con.close()

        db_mod.init_db(self.db_path)
        with db_mod.connection(self.db_path) as con2:
            tables = {r["name"] for r in con2.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            v = con2.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        self.assertIn("account_usage_reports", tables)
        self.assertIn("providers", tables)
        self.assertIn("accounts", tables)
        self.assertEqual(int(v["value"]), db_mod.SCHEMA_VERSION)

    def test_insert_and_dedupe_with_null_workspace(self):
        """Rows with NULL workspace_id/model must still dedupe (COALESCE index)."""
        db_mod.init_db(self.db_path)
        row = {
            "source": "manual_account_import", "report_start": "2026-07-01",
            "report_end": "2026-07-01", "account_profile": "default",
            "organization_id": None, "workspace_id": None, "user_email_hash": None,
            "model": None, "service": "tokens",
            "input_tokens": 100, "output_tokens": 50, "cache_read_tokens": None,
            "cache_write_tokens": None, "total_tokens": 150,
            "cost_value": 1.23, "cost_currency": "USD",
            "raw_source_reference": "test.csv", "imported_at": "2026-07-01T00:00:00Z",
            "confidence": "manually_entered",
        }
        with db_mod.connection(self.db_path) as con:
            first = db_mod.insert_account_usage_row(con, row)
            second = db_mod.insert_account_usage_row(con, row)
        self.assertTrue(first)
        self.assertFalse(second)  # must be deduped, not a second row


class TestManualImportCSV(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "csv.sqlite"
        db_mod.init_db(self.db_path)
        self.csv_path = Path(self.tmp_dir.name) / "export.csv"
        self.csv_path.write_text(
            "period,model,description,amount,currency\n"
            "2026-07-01,claude-opus-4-8,Usage - Input Tokens,10.50,USD\n"
            "2026-07-01,claude-opus-4-8,Usage - Output Tokens,25.00,USD\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_sniff_format_csv(self):
        self.assertEqual(manual_import.sniff_format(self.csv_path), "csv")

    def test_preview_detects_columns(self):
        preview = manual_import.preview(self.csv_path)
        self.assertEqual(preview["total_rows"], 2)
        self.assertEqual(preview["column_mapping"]["cost_value"], "amount")
        self.assertEqual(preview["column_mapping"]["model"], "model")

    def test_preview_never_imports(self):
        manual_import.preview(self.csv_path)
        with db_mod.connection(self.db_path) as con:
            count = con.execute("SELECT COUNT(*) n FROM account_usage_reports").fetchone()["n"]
        self.assertEqual(count, 0)

    @patch("token_consumption.db._db_path")
    def test_dry_run_writes_nothing(self, mock_dbpath):
        mock_dbpath.return_value = self.db_path
        result = manual_import.import_file(self.csv_path, dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["imported"], 0)
        self.assertEqual(result["would_import"], 2)

    @patch("token_consumption.db._db_path")
    def test_commit_writes_rows(self, mock_dbpath):
        mock_dbpath.return_value = self.db_path
        result = manual_import.import_file(self.csv_path, dry_run=False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["imported"], 2)
        with db_mod.connection(self.db_path) as con:
            rows = con.execute("SELECT * FROM account_usage_reports").fetchall()
        self.assertEqual(len(rows), 2)
        for r in rows:
            self.assertEqual(r["source"], "manual_account_import")
            self.assertEqual(r["confidence"], "manually_entered")

    @patch("token_consumption.db._db_path")
    def test_reimport_is_idempotent(self, mock_dbpath):
        mock_dbpath.return_value = self.db_path
        manual_import.import_file(self.csv_path, dry_run=False)
        result2 = manual_import.import_file(self.csv_path, dry_run=False)
        self.assertEqual(result2["imported"], 0)

    def test_forbidden_columns_never_imported(self):
        bad_csv = Path(self.tmp_dir.name) / "bad.csv"
        bad_csv.write_text("period,amount,prompt\n2026-07-01,5.00,ignore me\n", encoding="utf-8")
        preview = manual_import.preview(bad_csv)
        self.assertIn("prompt", preview["forbidden_columns"])
        rows = manual_import._read_rows(bad_csv, "csv")
        mapping = manual_import.detect_columns(rows)
        normalized = manual_import.to_account_usage_rows(bad_csv, rows, mapping)
        for row in normalized:
            self.assertNotIn("prompt", row)
            for v in row.values():
                self.assertNotEqual(v, "ignore me")


class TestManualImportJSON(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "json.sqlite"
        db_mod.init_db(self.db_path)
        self.json_path = Path(self.tmp_dir.name) / "export.json"
        self.json_path.write_text(json.dumps([
            {"period": "2026-07-01", "model": "claude-sonnet-4-6", "amount": "3.00", "currency": "USD"},
            {"period": "2026-07-02", "model": "claude-sonnet-4-6", "amount": "4.50", "currency": "USD"},
        ]), encoding="utf-8")

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_sniff_format_json(self):
        self.assertEqual(manual_import.sniff_format(self.json_path), "json")

    def test_preview_json(self):
        preview = manual_import.preview(self.json_path)
        self.assertEqual(preview["total_rows"], 2)
        self.assertEqual(preview["format"], "json")

    @patch("token_consumption.db._db_path")
    def test_commit_json(self, mock_dbpath):
        mock_dbpath.return_value = self.db_path
        result = manual_import.import_file(self.json_path, dry_run=False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["imported"], 2)

    def test_json_wrapped_in_items_key(self):
        wrapped = Path(self.tmp_dir.name) / "wrapped.json"
        wrapped.write_text(json.dumps({"items": [{"period": "2026-07-01", "amount": "1.00"}]}),
                          encoding="utf-8")
        preview = manual_import.preview(wrapped)
        self.assertEqual(preview["total_rows"], 1)


class TestAnthropicAccountConnector(unittest.TestCase):
    """All tests here mock urllib — no real network calls are made."""

    def setUp(self):
        self.env_patcher = patch.dict("os.environ", {}, clear=False)
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()

    def test_mask_key_short(self):
        self.assertEqual(anthropic_account.mask_key("short"), "*****")

    def test_mask_key_long_never_shows_middle(self):
        key = "sk-ant-admin01-abcdefghijklmnopqrstuvwxyz"
        masked = anthropic_account.mask_key(key)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz"[:-4], masked)
        self.assertTrue(masked.startswith("sk-ant-admin"))
        self.assertTrue(masked.endswith(key[-4:]))

    def test_mask_key_none(self):
        self.assertEqual(anthropic_account.mask_key(None), "(not set)")

    @patch.dict("os.environ", {}, clear=True)
    def test_no_key_returns_clear_message(self):
        result = anthropic_account.test_connection()
        self.assertFalse(result["ok"])
        self.assertIn("ANTHROPIC_ADMIN_API_KEY", result["message"])

    @patch.dict("os.environ", {"ANTHROPIC_ADMIN_API_KEY": "sk-ant-admin01-testkey1234567890"})
    @patch("urllib.request.urlopen")
    def test_401_maps_to_clear_message(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "url", 401, "Unauthorized", {}, io.BytesIO(b'{"error":{"message":"invalid key"}}'))
        result = anthropic_account.test_connection()
        self.assertFalse(result["ok"])
        self.assertEqual(result["status_code"], 401)
        self.assertIn("invalid", result["message"].lower())

    @patch.dict("os.environ", {"ANTHROPIC_ADMIN_API_KEY": "sk-ant-admin01-testkey1234567890"})
    @patch("urllib.request.urlopen")
    def test_403_maps_to_permission_denied(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "url", 403, "Forbidden", {}, io.BytesIO(b'{}'))
        result = anthropic_account.test_connection()
        self.assertFalse(result["ok"])
        self.assertEqual(result["status_code"], 403)
        self.assertIn("permission", result["message"].lower())

    @patch.dict("os.environ", {"ANTHROPIC_ADMIN_API_KEY": "sk-ant-admin01-testkey1234567890"})
    @patch("urllib.request.urlopen")
    def test_404_maps_to_unavailable_for_account(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "url", 404, "Not Found", {}, io.BytesIO(b'{}'))
        result = anthropic_account.test_connection()
        self.assertFalse(result["ok"])
        self.assertEqual(result["status_code"], 404)
        self.assertIn("unavailable", result["message"].lower())

    @patch.dict("os.environ", {"ANTHROPIC_ADMIN_API_KEY": "sk-ant-admin01-testkey1234567890"})
    @patch("urllib.request.urlopen")
    def test_success_response(self, mock_urlopen):
        fake_resp = MagicMock()
        fake_resp.read.return_value = json.dumps({"data": [], "has_more": False}).encode()
        fake_resp.__enter__.return_value = fake_resp
        mock_urlopen.return_value = fake_resp
        result = anthropic_account.test_connection()
        self.assertTrue(result["ok"])
        self.assertEqual(result["status_code"], 200)

    @patch.dict("os.environ", {"ANTHROPIC_ADMIN_API_KEY": "sk-ant-admin01-SECRETVALUE9999"})
    @patch("urllib.request.urlopen")
    def test_no_secret_leakage_on_error(self, mock_urlopen):
        """The full key must never appear in a raised error's message."""
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "url", 401, "Unauthorized", {}, io.BytesIO(b'{}'))
        result = anthropic_account.test_connection()
        self.assertNotIn("SECRETVALUE9999", result["message"])
        self.assertNotIn("SECRETVALUE9999", str(result))

    @patch.dict("os.environ", {"ANTHROPIC_ADMIN_API_KEY": "sk-ant-admin01-SECRETVALUE9999"})
    def test_no_secret_leakage_in_masked_key(self):
        masked = anthropic_account.mask_key(anthropic_account.get_api_key())
        self.assertNotIn("SECRETVALUE9999", masked)

    @patch.dict("os.environ", {}, clear=True)
    def test_sync_without_key_records_error_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "sync.sqlite"
            db_mod.init_db(db_path)
            with patch("token_consumption.db._db_path", return_value=db_path):
                result = anthropic_account.sync("2026-07-01T00:00:00Z", "2026-07-02T00:00:00Z")
            self.assertFalse(result["ok"])
            self.assertIn("ANTHROPIC_ADMIN_API_KEY", result["error"])


class TestReconciliation(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "recon.sqlite"
        db_mod.init_db(self.db_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _insert_turn(self, con, ts, cost):
        con.execute("""
            INSERT INTO turns (turn_uuid, session_id, ts, role, model, cost_total, cost_currency)
            VALUES (?, 's1', ?, 'assistant', 'claude-opus-4-8', ?, 'USD')
        """, (f"uuid-{ts}", ts, cost))

    def test_no_reference_data_returns_none(self):
        from token_consumption import estimate as estimate_mod
        with db_mod.connection(self.db_path) as con:
            self._insert_turn(con, "2026-07-01T00:00:00Z", 10.0)
        result = estimate_mod.calibration_summary("2026-07-01", "2026-07-02", db_path=self.db_path)
        self.assertIsNone(result)

    def test_calibration_math(self):
        from token_consumption import estimate as estimate_mod
        with db_mod.connection(self.db_path) as con:
            self._insert_turn(con, "2026-07-01T00:00:00Z", 12.0)  # local total = 12
            db_mod.insert_account_usage_row(con, {
                "source": "anthropic_admin_api", "report_start": "2026-07-01",
                "report_end": "2026-07-01", "account_profile": "default",
                "organization_id": None, "workspace_id": None, "user_email_hash": None,
                "model": "claude-opus-4-8", "service": "tokens",
                "input_tokens": None, "output_tokens": None, "cache_read_tokens": None,
                "cache_write_tokens": None, "total_tokens": None,
                "cost_value": 10.0, "cost_currency": "USD",  # official total = 10
                "raw_source_reference": "api", "imported_at": "2026-07-01T00:00:00Z",
                "confidence": "exact",
            })
        result = estimate_mod.calibration_summary("2026-07-01", "2026-07-02", db_path=self.db_path)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["local_cost_usd"], 12.0)
        self.assertAlmostEqual(result["reference_cost_usd"], 10.0)
        self.assertAlmostEqual(result["diff_pct"], 20.0, places=1)  # 12 vs 10 = +20%
        self.assertEqual(result["reference_source"], "official Admin API")

    def test_prefers_official_over_manual(self):
        from token_consumption import estimate as estimate_mod
        with db_mod.connection(self.db_path) as con:
            self._insert_turn(con, "2026-07-01T00:00:00Z", 10.0)
            for source, cost in (("anthropic_admin_api", 9.0), ("manual_account_import", 5.0)):
                db_mod.insert_account_usage_row(con, {
                    "source": source, "report_start": "2026-07-01", "report_end": "2026-07-01",
                    "account_profile": "default", "organization_id": None, "workspace_id": None,
                    "user_email_hash": None, "model": "claude-opus-4-8", "service": "tokens",
                    "input_tokens": None, "output_tokens": None, "cache_read_tokens": None,
                    "cache_write_tokens": None, "total_tokens": None,
                    "cost_value": cost, "cost_currency": "USD",
                    "raw_source_reference": source, "imported_at": "2026-07-01T00:00:00Z",
                    "confidence": "exact" if source == "anthropic_admin_api" else "manually_entered",
                })
        result = estimate_mod.calibration_summary("2026-07-01", "2026-07-02", db_path=self.db_path)
        self.assertEqual(result["reference_source"], "official Admin API")
        self.assertAlmostEqual(result["reference_cost_usd"], 9.0)


if __name__ == "__main__":
    unittest.main()
