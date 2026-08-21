"""
Verify the AI Command Center hub pages return 200 and never render a
password field. Uses FastAPI's TestClient — no real server/socket.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from token_consumption import db as db_mod


class TestHubPages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            raise unittest.SkipTest("fastapi/httpx not installed — skipping UI tests")

        cls.tmp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.tmp_dir.name) / "hub.sqlite"
        db_mod.init_db(cls.db_path)

        cls.db_patcher = patch("token_consumption.db._db_path", return_value=cls.db_path)
        cls.db_patcher.start()

        from token_consumption.ui.app import create_app
        cls.client = TestClient(create_app())

    @classmethod
    def tearDownClass(cls):
        cls.db_patcher.stop()
        cls.tmp_dir.cleanup()

    def _assert_no_password_or_login_fields(self, content: bytes):
        self.assertNotIn(b'type="password"', content)
        self.assertNotIn(b'name="password"', content)
        self.assertNotIn(b'name="email"', content)

    def test_overview_still_200_after_hub_revamp(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)

    def test_providers_list_200(self):
        r = self.client.get("/providers")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Claude / Anthropic", r.content)
        self._assert_no_password_or_login_fields(r.content)

    def test_provider_detail_200(self):
        r = self.client.get("/providers/anthropic")
        self.assertEqual(r.status_code, 200)
        self._assert_no_password_or_login_fields(r.content)

    def test_provider_detail_unknown_200_not_found_message(self):
        r = self.client.get("/providers/does-not-exist")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"not found", r.content.lower())

    def test_provider_connect_200_no_password(self):
        r = self.client.get("/providers/openai/connect")
        self.assertEqual(r.status_code, 200)
        self._assert_no_password_or_login_fields(r.content)

    def test_ai_accounts_list_200(self):
        r = self.client.get("/accounts")
        self.assertEqual(r.status_code, 200)

    def test_ai_accounts_add_get_200(self):
        r = self.client.get("/accounts/add")
        self.assertEqual(r.status_code, 200)
        self._assert_no_password_or_login_fields(r.content)

    def test_ai_accounts_add_roundtrip(self):
        r = self.client.post("/accounts/add", data={
            "provider": "openai",
            "label": "test-label",
            "plan": "Plus",
            "monthly_price": "20",
            "currency": "USD",
            "status": "manual",
            "notes": "",
        }, follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"test-label", r.content)

    def test_local_sources_200(self):
        r = self.client.get("/local-sources")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"machine only", r.content)

    def test_workflows_200_no_goal(self):
        r = self.client.get("/workflows")
        self.assertEqual(r.status_code, 200)

    def test_workflows_suggests_for_known_goal(self):
        r = self.client.get("/workflows", params={"goal": "help me refactor some code"})
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Claude", r.content)

    def test_workflows_no_external_call_disclaimer_present(self):
        r = self.client.get("/workflows")
        self.assertIn(b"no external model", r.content.lower())


if __name__ == "__main__":
    unittest.main()
