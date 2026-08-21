# Roadmap

## Shipped

- Phase 1–2: local Claude Code tracking (JSONL ingest, pricing, estimator,
  hooks, statusLine, dashboard).
- Phase 3: Account Data integration (Admin API connector, manual import,
  manual balance snapshots, reconciliation).
- Phase 4 (this phase): AI Command Center foundational slice — provider
  registry, manual account/subscription tracking, metadata-only local
  source scanner, overview revamp, `/workflows` static demo.

## Deferred from Phase 4 (explicitly out of scope this round)

- **Real workflow execution.** `/workflows` is a static, rule-based keyword
  demo only — no external model call, no actual task execution. A real
  version would need explicit design work on how/whether to call out to
  other providers, which is a much bigger scope decision.
- **Credit/included-allowance modeling.** Accounts store a flat monthly
  price; they don't model prepaid credit pools, resets, or netting local
  estimates against "spend after credits." See
  [CONNECTED_ACCOUNTS.md](CONNECTED_ACCOUNTS.md).
- **Official cost APIs for non-Claude providers.** OpenAI/Gemini org-level
  usage APIs exist for API-billing customers but aren't wired up. Manual
  import (`tc import-account`) already works for any CSV/JSON export
  regardless of provider, so this is partially covered.
- **Multi-currency FX.** Only USD→EUR conversion is implemented; other
  currencies are summed at face value.
- **A UI "add custom provider" form.** Custom providers currently require
  the CLI (`tc providers add`).
- **OS keyring support.** API keys remain env-var-only by design (smaller
  attack surface, easier to audit) — unchanged from Phase 3.
- **Cloud sync / multi-machine view.** Local sources are explicitly labeled
  machine-local; there's no mechanism yet to aggregate across machines.
- **TokenConsumption login/auth.** Still a single-user, localhost-only tool.

## Not yet done from earlier phases (still open)

- Estimate learning loop (backfill `estimates.linked_turn_uuid` + accuracy
  trend in UI).
- Per-task-type classification on turns.
- Anomaly detection page (turns > 3σ).
- Settings-page toggle for `prefer_official_account_costs`.
