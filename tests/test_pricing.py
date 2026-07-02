"""Unit tests for pricing.py."""

import json
import tempfile
import unittest
from pathlib import Path

# Ensure src/ is importable when running from project root
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from token_consumption.pricing import PricingTable, CostResult


PRICING_WITH_RATES = {
    "version": "test-1.0",
    "currency": "USD",
    "models": {
        "claude-test-model": {
            "rates_per_mtoken": {
                "input": 15.0,
                "output": 75.0,
                "cache_read": 1.5,
                "cache_write_5m": 3.75,
                "cache_write_1h": None,
            }
        },
        "claude-unpriced": {
            "rates_per_mtoken": {
                "input": None,
                "output": None,
                "cache_read": None,
                "cache_write_5m": None,
                "cache_write_1h": None,
            }
        },
    }
}


class TestPricingTable(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump(PRICING_WITH_RATES, self.tmp)
        self.tmp.close()  # Must close on Windows before reading or deleting
        self.table = PricingTable(Path(self.tmp.name))

    def test_version(self):
        self.assertEqual(self.table.version, "test-1.0")

    def test_currency(self):
        self.assertEqual(self.table.currency, "USD")

    def test_known_model_rates(self):
        rates = self.table.rates_for("claude-test-model")
        self.assertEqual(rates["input"], 15.0)
        self.assertEqual(rates["output"], 75.0)
        self.assertEqual(rates["cache_read"], 1.5)

    def test_unknown_model_returns_none_rates(self):
        rates = self.table.rates_for("claude-nonexistent")
        self.assertIsNone(rates["input"])
        self.assertIsNone(rates["output"])

    def test_cost_calculation_basic(self):
        result = self.table.compute_cost(
            model="claude-test-model",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        self.assertIsInstance(result, CostResult)
        self.assertAlmostEqual(result.input_cost, 15.0, places=4)
        self.assertAlmostEqual(result.output_cost, 75.0, places=4)
        self.assertAlmostEqual(result.total_cost, 90.0, places=4)

    def test_cost_calculation_small(self):
        # 1500 input, 800 output — typical small turn
        result = self.table.compute_cost(
            model="claude-test-model",
            input_tokens=1500,
            output_tokens=800,
        )
        expected_in = 1500 * 15.0 / 1_000_000
        expected_out = 800 * 75.0 / 1_000_000
        self.assertAlmostEqual(result.input_cost, expected_in, places=6)
        self.assertAlmostEqual(result.output_cost, expected_out, places=6)

    def test_cache_read_cost(self):
        result = self.table.compute_cost(
            model="claude-test-model",
            cache_read_tokens=5_000_000,
        )
        self.assertAlmostEqual(result.cache_read_cost, 7.5, places=4)

    def test_zero_tokens_gives_zero_cost(self):
        result = self.table.compute_cost(
            model="claude-test-model",
            input_tokens=0,
            output_tokens=0,
        )
        self.assertEqual(result.input_cost, 0.0)
        self.assertEqual(result.output_cost, 0.0)

    def test_unpriced_model_returns_none_costs(self):
        result = self.table.compute_cost(
            model="claude-unpriced",
            input_tokens=1000,
            output_tokens=500,
        )
        self.assertIsNone(result.input_cost)
        self.assertIsNone(result.output_cost)
        self.assertIsNone(result.total_cost)

    def test_unknown_model_returns_none_costs(self):
        result = self.table.compute_cost(
            model="claude-does-not-exist",
            input_tokens=1000,
        )
        self.assertIsNone(result.total_cost)

    def tearDown(self):
        Path(self.tmp.name).unlink(missing_ok=True)


PRICING_WITH_1H_AND_ALIASES = {
    "version": "test-2.0",
    "currency": "USD",
    "aliases": {"claude-full-name-20990101": "claude-canonical"},
    "models": {
        "claude-canonical": {
            "rates_per_mtoken": {
                "input": 5.0, "output": 25.0, "cache_read": 0.5,
                "cache_write_5m": 6.25, "cache_write_1h": 10.0,
            }
        }
    }
}


class TestAliasesAndCacheWrite1h(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump(PRICING_WITH_1H_AND_ALIASES, self.tmp)
        self.tmp.close()
        self.table = PricingTable(Path(self.tmp.name))

    def tearDown(self):
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_alias_resolves(self):
        self.assertEqual(self.table.resolve_alias("claude-full-name-20990101"), "claude-canonical")
        self.assertTrue(self.table.is_known("claude-full-name-20990101"))

    def test_alias_rates_match_canonical(self):
        aliased = self.table.rates_for("claude-full-name-20990101")
        canonical = self.table.rates_for("claude-canonical")
        self.assertEqual(aliased, canonical)
        self.assertEqual(aliased["input"], 5.0)

    def test_unknown_model_not_known(self):
        self.assertFalse(self.table.is_known("claude-does-not-exist"))

    def test_cache_write_1h_priced_separately(self):
        result = self.table.compute_cost(
            model="claude-canonical",
            cache_write_1h_tokens=1_000_000,
        )
        # 1h rate is 10.0/Mtoken
        self.assertAlmostEqual(result.cache_write_cost, 10.0, places=4)

    def test_cache_write_5m_and_1h_sum(self):
        result = self.table.compute_cost(
            model="claude-canonical",
            cache_write_5m_tokens=1_000_000,   # 6.25
            cache_write_1h_tokens=1_000_000,   # 10.00
        )
        self.assertAlmostEqual(result.cache_write_cost, 16.25, places=4)

    def test_alias_compute_cost(self):
        result = self.table.compute_cost(
            model="claude-full-name-20990101",
            input_tokens=1_000_000,
        )
        self.assertAlmostEqual(result.input_cost, 5.0, places=4)


class TestCacheWriteSplitNoDoubleCount(unittest.TestCase):
    """The module-level compute_cost must not double-count cache-write tokens."""

    def setUp(self):
        from token_consumption import pricing as p
        self.p = p
        self.tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump(PRICING_WITH_1H_AND_ALIASES, self.tmp)
        self.tmp.close()
        self.p._table = PricingTable(Path(self.tmp.name))  # inject singleton

    def tearDown(self):
        self.p._table = None
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_split_prefers_breakdown(self):
        usage = {
            "cache_creation_input_tokens": 1000,
            "cache_creation": {"ephemeral_5m_input_tokens": 700, "ephemeral_1h_input_tokens": 300},
        }
        cw5, cw1 = self.p._split_cache_write(usage)
        self.assertEqual((cw5, cw1), (700, 300))  # not 1000+700

    def test_split_fallback_to_total_as_5m(self):
        usage = {"cache_creation_input_tokens": 500}
        cw5, cw1 = self.p._split_cache_write(usage)
        self.assertEqual((cw5, cw1), (500, 0))

    def test_compute_cost_from_usage_block(self):
        usage = {
            "input_tokens": 1_000_000, "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 1_000_000,
            "cache_creation": {"ephemeral_5m_input_tokens": 1_000_000, "ephemeral_1h_input_tokens": 0},
        }
        result = self.p.compute_cost("claude-canonical", usage)
        # input 5.0 + cache_write_5m 6.25 = 11.25 (NOT double-counted)
        self.assertAlmostEqual(result.total_cost, 11.25, places=4)


if __name__ == "__main__":
    unittest.main()
