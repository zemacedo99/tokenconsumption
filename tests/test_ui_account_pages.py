"""
Verify the account-data UI pages return 200 and never render a password field
or leak a full API key. Uses FastAPI's TestClient — no real server/socket.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from token_consumption import db as db_mod


class TestAccountPages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            raise unittest.SkipTest("fastapi/httpx not installed — skipping UI tests")

        cls.tmp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.tmp_dir.name) / "ui.sqlite"
        db_mod.init_db(cls.db_path)

        cls.db_patcher = patch("token_consumption.db._db_path", return_value=cls.db_path)
        cls.db_patcher.start()

        from token_consumption.ui.app import create_app
        cls.client = TestClient(create_app())

    @classmethod
    def tearDownClass(cls):
        cls.db_patcher.stop()
        cls.tmp_dir.cleanup()

    def test_overview_200(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)

    def test_account_200(self):
        r = self.client.get("/account")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"local_claude_code_jsonl", r.content)

    def test_account_connect_200(self):
        r = self.client.get("/account/connect")
        self.assertEqual(r.status_code, 200)

    def test_account_connect_no_password_field(self):
        """The page may explain 'we don't ask for a password' in prose — that's
        fine and intentional. What must never exist is an actual input field
        that collects one."""
        r = self.client.get("/account/connect")
        self.assertNotIn(b'type="password"', r.content)
        self.assertNotIn(b'name="password"', r.content)
        self.assertNotIn(b'name="email"', r.content)

    def test_account_import_200(self):
        r = self.client.get("/account/import")
        self.assertEqual(r.status_code, 200)

    def test_account_reconcile_200(self):
        r = self.client.get("/account/reconcile")
        self.assertEqual(r.status_code, 200)

    def test_settings_200(self):
        r = self.client.get("/settings")
        self.assertEqual(r.status_code, 200)

    @patch.dict("os.environ", {"ANTHROPIC_ADMIN_API_KEY": "sk-ant-admin01-SECRETVALUE9999"})
    def test_connect_test_never_leaks_full_key(self):
        r = self.client.post("/account/connect/test")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn(b"SECRETVALUE9999", r.content)

    def test_balance_snapshot_roundtrip(self):
        r = self.client.post("/account/snapshot", data={
            "plan_name": "Max 20x",
            "monthly_budget_value": "200",
            "monthly_budget_currency": "USD",
            "usage_credits_total": "1000",
            "usage_credits_remaining": "400",
            "usage_credits_used": "600",
            "reset_date": "2026-08-01",
            "notes": "manual test entry",
        }, follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Max 20x", r.content)


if __name__ == "__main__":
    unittest.main()
