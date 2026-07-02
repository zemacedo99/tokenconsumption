"""Calculate token costs from pricing.json. Gracefully handles null/missing rates.

Supports model aliases (exact local model name -> canonical priced name) and
separate 5-minute and 1-hour cache-write rates.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from . import config as cfg_mod


@dataclass
class CostResult:
    input_cost: float | None
    output_cost: float | None
    cache_read_cost: float | None
    cache_write_cost: float | None
    total_cost: float | None
    currency: str
    pricing_version: str
    is_fully_priced: bool  # False if any relevant rate (for used token type) was null


class PricingTable:
    def __init__(self, pricing_path: Path | None = None):
        path = pricing_path or cfg_mod._pricing_path()
        try:
            self._data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[tc:pricing] Warning: could not load pricing.json: {exc}")
            self._data = {}

    @property
    def version(self) -> str:
        return self._data.get("version", "unknown")

    @property
    def currency(self) -> str:
        return self._data.get("currency", "USD")

    def resolve_alias(self, model: str) -> str:
        """Resolve an alias to its canonical model key. Returns model unchanged if no alias."""
        aliases = self._data.get("aliases", {})
        return aliases.get(model, model)

    def is_known(self, model: str) -> bool:
        """True if the (alias-resolved) model exists in the pricing table."""
        canonical = self.resolve_alias(model)
        return canonical in self._data.get("models", {})

    def rates_for(self, model: str) -> dict:
        """Return rates_per_mtoken dict for a model (alias-resolved), or all-None if unknown."""
        canonical = self.resolve_alias(model)
        entry = self._data.get("models", {}).get(canonical, {})
        rates = entry.get("rates_per_mtoken", {})
        return {
            "input": rates.get("input"),
            "output": rates.get("output"),
            "cache_read": rates.get("cache_read"),
            "cache_write_5m": rates.get("cache_write_5m"),
            "cache_write_1h": rates.get("cache_write_1h"),
        }

    def compute_cost(
        self,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_write_5m_tokens: int = 0,
        cache_write_1h_tokens: int = 0,
    ) -> CostResult:
        rates = self.rates_for(model)

        def _cost(tokens: int, rate: float | None) -> float | None:
            if tokens == 0:
                return 0.0
            if rate is None:
                return None
            return tokens * rate / 1_000_000

        cost_input = _cost(input_tokens, rates["input"])
        cost_output = _cost(output_tokens, rates["output"])
        cost_cache_read = _cost(cache_read_tokens, rates["cache_read"])

        # 5m and 1h cache writes priced separately; fall back to the other rate if one is null.
        rate_5m = rates["cache_write_5m"] if rates["cache_write_5m"] is not None else rates["cache_write_1h"]
        rate_1h = rates["cache_write_1h"] if rates["cache_write_1h"] is not None else rates["cache_write_5m"]
        cost_cw_5m = _cost(cache_write_5m_tokens, rate_5m)
        cost_cw_1h = _cost(cache_write_1h_tokens, rate_1h)
        cw_parts = [c for c in (cost_cw_5m, cost_cw_1h) if c is not None]
        cost_cache_write: float | None = sum(cw_parts) if cw_parts else None
        # If any used cache-write bucket is unpriced, mark write cost unknown.
        if (cache_write_5m_tokens > 0 and cost_cw_5m is None) or (
            cache_write_1h_tokens > 0 and cost_cw_1h is None
        ):
            cost_cache_write = None

        token_cost_pairs = [
            (input_tokens, cost_input),
            (output_tokens, cost_output),
            (cache_read_tokens, cost_cache_read),
            (cache_write_5m_tokens + cache_write_1h_tokens, cost_cache_write),
        ]
        is_fully_priced = all(
            cost is not None for tokens, cost in token_cost_pairs if tokens > 0
        )

        # If any USED token bucket is unpriced, the total is unknown (None) rather
        # than an understated, fabricated number. Fully-priced (incl. zero-usage)
        # sums normally.
        if is_fully_priced:
            total: float | None = sum(
                p for p in (cost_input, cost_output, cost_cache_read, cost_cache_write) if p is not None
            )
        else:
            total = None

        return CostResult(
            input_cost=cost_input,
            output_cost=cost_output,
            cache_read_cost=cost_cache_read,
            cache_write_cost=cost_cache_write,
            total_cost=total,
            currency=self.currency,
            pricing_version=self.version,
            is_fully_priced=is_fully_priced,
        )


# Module-level singleton (lazy-loaded)
_table: PricingTable | None = None


def get_table(reload: bool = False) -> PricingTable:
    global _table
    if _table is None or reload:
        _table = PricingTable()
    return _table


def _split_cache_write(usage: dict) -> tuple[int, int]:
    """
    Return (cache_write_5m_tokens, cache_write_1h_tokens) from a usage block,
    avoiding double-counting.

    Claude Code usage blocks provide a total `cache_creation_input_tokens` and,
    when available, a `cache_creation` breakdown into ephemeral_5m/1h. Prefer the
    breakdown; otherwise treat the whole total as 5m (the default TTL).
    """
    cache_creation = usage.get("cache_creation") or {}
    if isinstance(cache_creation, dict) and (
        "ephemeral_5m_input_tokens" in cache_creation
        or "ephemeral_1h_input_tokens" in cache_creation
    ):
        return (
            cache_creation.get("ephemeral_5m_input_tokens", 0),
            cache_creation.get("ephemeral_1h_input_tokens", 0),
        )
    return usage.get("cache_creation_input_tokens", 0), 0


def compute_cost(model: str, usage: dict) -> CostResult:
    """
    Convenience function. `usage` is the JSONL usage block:
    {input_tokens, output_tokens, cache_read_input_tokens,
     cache_creation_input_tokens, cache_creation: {...}}
    """
    table = get_table()
    cw_5m, cw_1h = _split_cache_write(usage)
    return table.compute_cost(
        model=model,
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        cache_read_tokens=usage.get("cache_read_input_tokens", 0),
        cache_write_5m_tokens=cw_5m,
        cache_write_1h_tokens=cw_1h,
    )
