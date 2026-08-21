"""
Tests for the AI Command Center hub: provider registry, configured accounts,
and the metadata-only local source scanner.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from token_consumption import db as db_mod
from token_consumption import providers as providers_mod
from token_consumption import accounts as accounts_mod
from token_consumption import sources as sources_mod


class TestProviderRegistry(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "providers.sqlite"
        db_mod.init_db(self.db_path)
        self.patcher = patch("token_consumption.db._db_path", return_value=self.db_path)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.tmp_dir.cleanup()

    def test_builtin_providers_present(self):
        keys = {p["provider_key"] for p in providers_mod.list_providers()}
        for expected in ("anthropic", "openai", "github_copilot", "google_gemini",
                         "perplexity", "notion_ai"):
            self.assertIn(expected, keys)

    def test_add_custom_provider_appears_in_list(self):
        providers_mod.add_custom_provider(
            provider_key="my_tool", display_name="My Tool",
            connection_methods=["manual_entry"], limitations="none",
        )
        keys = {p["provider_key"] for p in providers_mod.list_providers()}
        self.assertIn("my_tool", keys)

    def test_custom_provider_cannot_shadow_builtin(self):
        with self.assertRaises(ValueError):
            providers_mod.add_custom_provider(provider_key="anthropic", display_name="Fake")

    def test_get_provider_unknown_returns_none(self):
        self.assertIsNone(providers_mod.get_provider("does_not_exist"))

    @patch.dict("os.environ", {}, clear=True)
    def test_status_unconfigured_when_no_env_no_account(self):
        self.assertEqual(providers_mod.provider_status("github_copilot"), "unconfigured")

    @patch.dict("os.environ", {"ANTHROPIC_ADMIN_API_KEY": "sk-ant-admin01-x"})
    def test_status_connected_when_env_var_set(self):
        self.assertEqual(providers_mod.provider_status("anthropic"), "connected")

    @patch.dict("os.environ", {}, clear=True)
    def test_status_manual_when_account_configured(self):
        accounts_mod.add_account(provider_key="openai", plan_name="Plus", monthly_price=20)
        self.assertEqual(providers_mod.provider_status("openai"), "manual")

    def test_status_unknown_for_missing_key(self):
        self.assertEqual(providers_mod.provider_status("nope"), "unknown")


class TestAccounts(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "accounts.sqlite"
        db_mod.init_db(self.db_path)
        self.patcher = patch("token_consumption.db._db_path", return_value=self.db_path)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.tmp_dir.cleanup()

    def test_add_and_list_account(self):
        accounts_mod.add_account(provider_key="openai", label="work", plan_name="Plus",
                                 monthly_price=20, price_currency="USD")
        accts = accounts_mod.list_accounts()
        self.assertEqual(len(accts), 1)
        self.assertEqual(accts[0]["provider_key"], "openai")
        self.assertEqual(accts[0]["confidence"], "manually_entered")

    def test_dedupe_same_provider_and_label(self):
        accounts_mod.add_account(provider_key="openai", label="work", monthly_price=20)
        second = accounts_mod.add_account(provider_key="openai", label="work", monthly_price=99)
        self.assertFalse(second)
        self.assertEqual(len(accounts_mod.list_accounts()), 1)

    def test_different_labels_do_not_dedupe(self):
        accounts_mod.add_account(provider_key="openai", label="work", monthly_price=20)
        accounts_mod.add_account(provider_key="openai", label="personal", monthly_price=20)
        self.assertEqual(len(accounts_mod.list_accounts()), 2)

    def test_monthly_total_converts_usd(self):
        accounts_mod.add_account(provider_key="openai", monthly_price=20, price_currency="USD")
        accounts_mod.add_account(provider_key="perplexity", monthly_price=10, price_currency="EUR")
        total = accounts_mod.monthly_subscription_total_eur()
        # USD converted via configured fx rate (default 0.92) + EUR at face value.
        self.assertAlmostEqual(total, 20 * 0.92 + 10, places=2)

    def test_status_summary(self):
        accounts_mod.add_account(provider_key="openai", monthly_price=20, price_currency="EUR")
        summary = accounts_mod.account_status_summary()
        self.assertEqual(summary["count"], 1)
        self.assertAlmostEqual(summary["monthly_total_eur"], 20.0)


class TestLocalSourcesScanner(unittest.TestCase):
    def test_scan_returns_expected_shape(self):
        results = sources_mod.scan()
        self.assertGreater(len(results), 0)
        for r in results:
            self.assertIn("tool", r)
            self.assertIn("exists", r)
            self.assertIn("file_count", r)
            self.assertTrue(r["machine_local"])
            self.assertIn("Found on this machine only", r["note"])
            # Never any content field.
            self.assertNotIn("content", r)
            self.assertNotIn("prompt", r)

    def test_probe_dir_never_opens_file_contents(self):
        """The scanner must only stat/glob — never read/open a file."""
        with tempfile.TemporaryDirectory() as tmp:
            secret_file = Path(tmp) / "secret.txt"
            secret_file.write_text("SUPER SECRET CONTENT", encoding="utf-8")
            info = sources_mod._probe_dir(Path(tmp))
            self.assertTrue(info["exists"])
            self.assertEqual(info["file_count"], 1)
            self.assertNotIn("SUPER SECRET CONTENT", str(info))

    def test_nonexistent_root_reports_not_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "does_not_exist"
            info = sources_mod._probe_dir(missing)
            self.assertFalse(info["exists"])
            self.assertEqual(info["file_count"], 0)

    def test_scan_summary_counts(self):
        summary = sources_mod.scan_summary()
        self.assertEqual(summary["total_checked"], len(summary["results"]))
        self.assertLessEqual(summary["found"], summary["total_checked"])


if __name__ == "__main__":
    unittest.main()
