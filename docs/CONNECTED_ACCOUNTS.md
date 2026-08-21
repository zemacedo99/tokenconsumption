# Connected accounts (manual subscription tracking)

`/accounts` and `tc accounts` track AI subscriptions/accounts you tell it
about — plan name, monthly price, currency, and a coarse status. This is
separate from (and simpler than) the Claude-specific Admin API / manual
import / reconciliation flow under `/account` (singular) — see
[ACCOUNT_DATA.md](ACCOUNT_DATA.md) for that.

## What's stored

Each account row: `provider_key`, optional `label` (to distinguish multiple
accounts on the same provider), `plan_name`, `monthly_price`,
`price_currency`, `billing_period`, `status`, `connection_method`, `notes`.
Confidence is always `manually_entered` in this phase — there is no
automated verification of what you type.

**No password, email, or API key value is ever stored in this table.** If a
provider has an API you use elsewhere, its key stays in your OS environment
(see [PROVIDERS.md](PROVIDERS.md) for the documented env var names per
provider — reference only).

## Adding an account

CLI:
```bash
tc accounts add --provider openai --plan "ChatGPT Plus" \
    --monthly-price 20 --currency USD --status manual
tc accounts list
tc accounts status
```

UI: `/accounts/add` — same fields, a plain HTML form, no password field.

## Monthly subscription total

`accounts.monthly_subscription_total_eur()` sums `monthly_price` across all
accounts. USD amounts are converted using the same FX rate configured for
the rest of the app (`config/budget_policy.json` → `fx_rates.USD_to_EUR`).
**Simplification:** any currency other than USD or EUR is currently added
at face value (no conversion) — fine for EUR-denominated accounts, but a
known rough edge for other currencies. A proper multi-currency FX table is
a documented follow-up (see [ROADMAP.md](ROADMAP.md)).

## Deduplication

Adding the same `provider_key` + `label` combination twice is a no-op (the
second insert is silently ignored) — use distinct labels ("work", "personal")
if you have more than one account with the same provider.

## Credit/allowance modeling

Deferred this phase. Accounts currently store a flat monthly price and
status only — they do not model included-credit pools, resets, or
usage-based overage. See project memory / [ROADMAP.md](ROADMAP.md) for why
this matters: reconciling local per-token cost estimates against a real
account with an included-credit pool needs credit-aware netting, not a
simple discount multiplier.
