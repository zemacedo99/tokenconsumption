# Reconciliation: local estimate vs official/manual account data

## Why costs can differ

Local cost is `exact token counts × config/pricing.json rates`. It will
diverge from official billing when:
- Pricing changed and `pricing.json` wasn't updated.
- Discounts, credits, or promotional pricing applied to your account.
- A model in your data isn't in `pricing.json` yet (shown as `unpriced`).
- Batch/priority service tiers billed differently than assumed.

## Where to look

- **UI:** `/account/reconcile` — shows local vs. official/manual cost per
  month, percentage difference, and a plain-English suggestion.
- **CLI:** `tc account status` shows source sync status; for the numeric
  comparison, use the reconcile UI page or call
  `token_consumption.estimate.calibration_summary(start, end)` directly.

## How the comparison works

For a given period:
1. Local cost = `SUM(turns.cost_total)` where the turn timestamp falls in the period.
2. Reference cost = official Admin API cost if any exists for the period,
   otherwise manual import cost, otherwise **no comparison is shown** (never
   fabricated).
3. `diff_pct = (local - reference) / reference * 100`.

## What TokenConsumption does with a mismatch

**It suggests, it does not act.** If local is 8% higher than official for a
period, you'll see:

> "Local estimate is 8.0% higher than official Admin API cost for 2026-07-01
> to 2026-07-31. Consider reviewing config/pricing.json rates (not applied
> automatically)."

`config/pricing.json` is **never modified automatically**. You decide whether
and how to adjust it.

## `prefer_official_account_costs`

A config flag (default `false`). When `true`:
- `tc status`, the statusLine footer, and the Overview page will use official
  (or, absent that, manual) cost for the **current month** wherever such data
  exists for that period, instead of the local pricing-table estimate.
- Per-turn detail (Sessions, Raw logs, Trends-by-model) always shows the local
  exact-token breakdown regardless of this setting — official data arrives
  pre-aggregated by day/model, not per-turn, so it can't replace that detail.

Enable it via:
```bash
tc config set prefer_official_account_costs true
```
(Not yet exposed as a Settings-page toggle — edit via CLI or
`config/budget_policy.json` directly.)
