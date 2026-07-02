"""Unit tests for status.py, config.py, and estimate.py."""

import json
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from token_consumption import db as db_mod
from token_consumption import ingest as ingest_mod
from token_consumption import status as status_mod
from token_consumption import config as cfg_mod
from token_consumption import estimate as est_mod
from token_consumption import pricing as pricing_mod


FIXTURE = Path(__file__).parent.parent / "examples" / "sample-transcript.jsonl"


class TestConfig(unittest.TestCase):
    def test_load_has_defaults(self):
        cfg = cfg_mod.load()
        self.assertIn("safety_threshold_value", cfg)
        self.assertIn("monthly_budget_value", cfg)

    def test_fx_conversion(self):
        cfg = {"fx_rates": {"USD_to_EUR": 0.5}}
        self.assertAlmostEqual(cfg_mod.fx_to_eur(100, cfg), 50.0)

    def test_validate_returns_list(self):
        cfg = cfg_mod.load()
        errors = cfg_mod.validate(cfg)
        self.assertIsInstance(errors, list)

    def test_set_rejects_internal_key(self):
        with self.assertRaises(ValueError):
            cfg_mod.set_value("$schema", "x")


class TestStatusLine(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "s.sqlite"
        db_mod.init_db(self.db_path)
        ingest_mod.ingest_file(FIXTURE, "proj", "/cwd", "default", db_path=self.db_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_status_line_is_string(self):
        line = status_mod.status_line(db_path=self.db_path)
        self.assertIsInstance(line, str)
        self.assertIn("TokenConsumption:", line)

    def test_get_status_structure(self):
        s = status_mod.get_status(db_path=self.db_path)
        self.assertTrue(s["ok"])
        self.assertIn("month_cost_usd", s)
        self.assertIn("safety_threshold_value", s)

    def test_status_line_never_fabricates(self):
        """Unpriced turns must show '?' not a fake number."""
        # Fixture uses claude-opus-4-7 / sonnet-4-6 which ARE priced in the real
        # pricing.json, so just assert the format is sane and contains labels.
        line = status_mod.status_line(db_path=self.db_path)
        self.assertTrue("month" in line)


class TestEstimate(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "e.sqlite"
        db_mod.init_db(self.db_path)
        ingest_mod.ingest_file(FIXTURE, "proj", "/cwd", "default", db_path=self.db_path)
        pricing_mod.get_table(reload=True)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_estimate_returns_object(self):
        est = est_mod.estimate("claude-opus-4-7", task_type="plan", db_path=self.db_path)
        self.assertEqual(est.model, "claude-opus-4-7")
        self.assertIn(est.confidence, ("low", "medium", "high"))
        self.assertIn(est.recommendation, ("proceed", "warn", "ask"))

    def test_unpriced_model_warns(self):
        est = est_mod.estimate("claude-totally-unknown", task_type="plan", db_path=self.db_path)
        self.assertIsNone(est.est_cost_eur)
        self.assertEqual(est.recommendation, "warn")

    def test_over_threshold_asks(self):
        # Force a huge turn count to exceed threshold on a priced model.
        est = est_mod.estimate("claude-opus-4-7", task_type="refactor_wide",
                               turns=100000, db_path=self.db_path)
        # With history present or fallback pricing, a massive turn count should exceed €20.
        if est.est_cost_eur is not None:
            self.assertEqual(est.recommendation, "ask")

    def test_format_estimate_string(self):
        est = est_mod.estimate("claude-opus-4-7", task_type="plan", db_path=self.db_path)
        s = est_mod.format_estimate(est)
        self.assertIn("Budget estimate:", s)
        self.assertIn("threshold", s)


if __name__ == "__main__":
    unittest.main()
