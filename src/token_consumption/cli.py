"""
TokenConsumption CLI entry point.

Usage:
  tc init
  tc import [--project PROJECT] [--since YYYY-MM-DD] [--verbose]
  tc log --session SESSION_ID [--verbose]
  tc status [--line | --json]
  tc report [--from YYYY-MM-DD] [--to YYYY-MM-DD]
  tc config get [KEY]
  tc config set KEY VALUE
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _require_module(name: str):
    """Lazy import to keep startup fast."""
    import importlib
    return importlib.import_module(f"token_consumption.{name}")


# ── Subcommand handlers ───────────────────────────────────────────────────────

def cmd_init(args: argparse.Namespace) -> int:
    cfg_mod = _require_module("config")
    db_mod = _require_module("db")

    # Create data/logs dirs
    cfg = cfg_mod.load()
    data_dir = cfg_mod._data_dir(cfg)
    data_dir.mkdir(parents=True, exist_ok=True)

    from pathlib import Path
    tool_root = cfg_mod._tool_root()
    (tool_root / "logs").mkdir(exist_ok=True)

    db_path = db_mod.init_db()
    print(f"[tc] Database initialised: {db_path}")

    # Copy example → local policy if absent
    example = cfg_mod._example_policy_path()
    local = cfg_mod._local_policy_path()
    if not local.exists() and example.exists():
        import shutil
        shutil.copy(example, local)
        print(f"[tc] Created {local} from example. Edit it to set your budget and threshold.")
    else:
        print(f"[tc] Budget policy: {local if local.exists() else '(using defaults)'}")

    print("[tc] Done. Next: fill config/pricing.json with your model rates, then run 'tc import'.")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    ingest_mod = _require_module("ingest")

    since_ts: str | None = None
    if args.since:
        try:
            datetime.strptime(args.since, "%Y-%m-%d")
            since_ts = args.since + "T00:00:00Z"
        except ValueError:
            print(f"[tc] Error: --since must be YYYY-MM-DD, got: {args.since!r}", file=sys.stderr)
            return 1

    totals = ingest_mod.ingest_all(
        project_filter=args.project,
        since_ts=since_ts,
        verbose=args.verbose,
    )
    print(
        f"[tc] Import complete: {totals['files']} files, "
        f"{totals['ingested']} turns ingested, "
        f"{totals['skipped']} skipped, "
        f"{totals['errors']} errors."
    )
    return 0


def cmd_log(args: argparse.Namespace) -> int:
    ingest_mod = _require_module("ingest")
    result = ingest_mod.ingest_session(args.session, verbose=args.verbose)
    print(
        f"[tc] Session log: {result['ingested']} turns ingested, "
        f"{result['errors']} errors."
    )
    return 0


def _session_id_from_stdin() -> str | None:
    """Claude Code pipes JSON (incl. session_id) to statusLine commands on stdin."""
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return None
        raw = sys.stdin.read()
        if not raw.strip():
            return None
        return json.loads(raw).get("session_id")
    except Exception:
        return None


def cmd_status(args: argparse.Namespace) -> int:
    status_mod = _require_module("status")
    session_id = _session_id_from_stdin() or os.environ.get("CLAUDE_CODE_SESSION_ID")

    if args.json:
        s = status_mod.get_status(session_id=session_id)
        print(json.dumps(s, indent=2))
    else:
        # --line is the default (also used when neither flag passed)
        print(status_mod.status_line(session_id=session_id))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    db_mod = _require_module("db")
    cfg_mod = _require_module("config")
    cfg = cfg_mod.load()
    account = cfg.get("account_profile_name", "default")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    from_date = args.from_date or "2020-01-01"
    to_date = args.to_date or today

    try:
        with db_mod.connection() as con:
            rows = con.execute("""
                SELECT
                    substr(ts, 1, 10)       AS day,
                    model,
                    project_slug,
                    COUNT(*)                AS turns,
                    SUM(total_tokens)       AS tokens,
                    SUM(cost_total)         AS cost_usd,
                    MAX(cost_currency)      AS currency
                FROM turns
                WHERE account_profile=?
                  AND substr(ts, 1, 10) BETWEEN ? AND ?
                GROUP BY day, model, project_slug
                ORDER BY day DESC, cost_usd DESC NULLS LAST
            """, (account, from_date, to_date)).fetchall()
    except Exception as exc:
        print(f"[tc] Report error: {exc}", file=sys.stderr)
        return 1

    if not rows:
        print(f"[tc] No data for {from_date} → {to_date}.")
        return 0

    print(f"\nTokenConsumption Report  {from_date} → {to_date}  (account: {account})")
    print(f"{'Day':<12} {'Model':<32} {'Project':<20} {'Turns':>6} {'Tokens':>10} {'Cost(USD)':>10}")
    print("-" * 100)
    total_cost = 0.0
    for r in rows:
        cost_str = f"${r['cost_usd']:.4f}" if r["cost_usd"] is not None else "  unpriced"
        if r["cost_usd"]:
            total_cost += r["cost_usd"]
        print(
            f"{r['day']:<12} {(r['model'] or 'unknown'):<32} "
            f"{(r['project_slug'] or ''):<20} {r['turns']:>6} "
            f"{(r['tokens'] or 0):>10,} {cost_str:>10}"
        )
    print("-" * 100)
    print(f"{'TOTAL':<76} ${total_cost:.4f}")
    fx = cfg.get("fx_rates", {}).get("USD_to_EUR", 0.92)
    print(f"      ≈ €{total_cost * fx:.2f} at configured rate {fx} USD/EUR")
    print()
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    cfg_mod = _require_module("config")

    if args.config_action == "get":
        if args.key:
            try:
                val, source = cfg_mod.get_value(args.key)
                print(f"{args.key} = {json.dumps(val)}  (source: {source})")
            except KeyError as e:
                print(str(e), file=sys.stderr)
                return 1
        else:
            cfg = cfg_mod.list_keys()
            for k, v in sorted(cfg.items()):
                print(f"{k} = {json.dumps(v)}")

    elif args.config_action == "set":
        if not args.key or args.value is None:
            print("[tc] Usage: tc config set <key> <value>", file=sys.stderr)
            return 1
        try:
            cfg_mod.set_value(args.key, args.value)
        except (KeyError, ValueError) as e:
            print(f"[tc] Error: {e}", file=sys.stderr)
            return 1

    else:
        print(f"[tc] Unknown config action: {args.config_action!r}", file=sys.stderr)
        return 1

    return 0


def cmd_estimate(args: argparse.Namespace) -> int:
    estimate_mod = _require_module("estimate")
    est = estimate_mod.estimate(
        model=args.model,
        task_type=args.task_type,
        prompt_tokens=args.prompt_tokens,
        turns=args.turns,
    )
    print(estimate_mod.format_estimate(est))
    if args.save:
        session_id = os.environ.get("CLAUDE_CODE_SESSION_ID")
        uuid = estimate_mod.save_estimate(est, session_id=session_id, project_slug=args.project)
        print(f"  (saved estimate metadata: {uuid})")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    try:
        from token_consumption.ui.app import run_server
    except ImportError as exc:
        print("[tc] UI dependencies not installed. Run:  pip install -e \".[ui]\"", file=sys.stderr)
        print(f"[tc] ({exc})", file=sys.stderr)
        return 1
    run_server(host=args.host, port=args.port)
    return 0


def cmd_import_account(args: argparse.Namespace) -> int:
    """Manual import of an official account/billing export (CSV/JSON). No scraping."""
    account_mod = _require_module("account")
    path = Path(args.file)
    if not path.exists():
        print(f"[tc] File not found: {path}", file=sys.stderr)
        return 1
    result = account_mod.import_account_export(path, verbose=args.verbose)
    print(f"[tc] Account import: {result}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    cfg_mod = _require_module("config")
    pricing_mod = _require_module("pricing")
    db_mod = _require_module("db")
    import json as _json
    from datetime import datetime as _dt

    print("TokenConsumption doctor\n" + "-" * 30)
    cfg = cfg_mod.load()

    # Config validation
    errors = cfg_mod.validate(cfg)
    print(f"[config] threshold={cfg.get('safety_threshold_value')} "
          f"{cfg.get('safety_threshold_currency')}, "
          f"monthly_budget={cfg.get('monthly_budget_value')} {cfg.get('monthly_budget_currency')}")
    print(f"[config] validation: {'OK' if not errors else 'ERRORS: ' + '; '.join(errors)}")

    # Pricing freshness + unpriced models in data
    table = pricing_mod.get_table()
    print(f"[pricing] version={table.version}, updated_at={table._data.get('updated_at', '?')}")
    db_path = db_mod._db_path()
    if db_path.exists():
        with db_mod.connection() as con:
            rows = con.execute(
                "SELECT DISTINCT model FROM turns WHERE model IS NOT NULL"
            ).fetchall()
        unknown = [r["model"] for r in rows if not table.is_known(r["model"])]
        if unknown:
            print(f"[pricing] UNPRICED/unknown models in data: {', '.join(unknown)}")
        else:
            print("[pricing] all models in data are priced")
        print(f"[db] {db_path} exists")
    else:
        print(f"[db] NOT FOUND at {db_path} — run 'tc init' then 'tc import'")

    # settings.json integration
    settings = Path.home() / ".claude" / "settings.json"
    if settings.exists():
        try:
            s = _json.loads(settings.read_text(encoding="utf-8-sig"))
            has_status = "statusLine" in s
            has_hooks = "Stop" in s.get("hooks", {})
            print(f"[claude] statusLine={'yes' if has_status else 'no'}, "
                  f"Stop hook={'yes' if has_hooks else 'no'}")
        except Exception as e:
            print(f"[claude] settings.json unreadable: {e}")
    else:
        print("[claude] no ~/.claude/settings.json — hooks not installed")

    claude_md = Path.home() / ".claude" / "CLAUDE.md"
    if claude_md.exists() and "TokenConsumption" in claude_md.read_text(encoding="utf-8"):
        print("[claude] global CLAUDE.md contains TokenConsumption section")
    else:
        print("[claude] global CLAUDE.md missing TokenConsumption section")

    return 0


# ── Argument parser ───────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tc",
        description="TokenConsumption — local Claude Code token/cost tracker",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # init
    sub.add_parser("init", help="Initialise database and config")

    # import
    p_import = sub.add_parser("import", help="Ingest all local Claude Code transcripts")
    p_import.add_argument("--project", metavar="NAME", help="Filter by project name (substring)")
    p_import.add_argument("--since", metavar="YYYY-MM-DD", help="Only ingest turns after this date")
    p_import.add_argument("--verbose", "-v", action="store_true")

    # log
    p_log = sub.add_parser("log", help="Ingest a specific session (used by Stop hook)")
    p_log.add_argument("--session", required=True, metavar="SESSION_ID")
    p_log.add_argument("--verbose", "-v", action="store_true")

    # status
    p_status = sub.add_parser("status", help="Show current usage status")
    status_group = p_status.add_mutually_exclusive_group()
    status_group.add_argument("--line", action="store_true", default=True,
                              help="Print one-line footer (default)")
    status_group.add_argument("--json", action="store_true",
                              help="Print full JSON status")

    # report
    p_report = sub.add_parser("report", help="Print a usage report")
    p_report.add_argument("--from", dest="from_date", metavar="YYYY-MM-DD")
    p_report.add_argument("--to", dest="to_date", metavar="YYYY-MM-DD")

    # config
    p_config = sub.add_parser("config", help="Get or set config values")
    config_sub = p_config.add_subparsers(dest="config_action", required=True)
    p_cfg_get = config_sub.add_parser("get", help="Get a config value")
    p_cfg_get.add_argument("key", nargs="?", help="Key to get (omit for all)")
    p_cfg_set = config_sub.add_parser("set", help="Set a config value")
    p_cfg_set.add_argument("key", help="Key to set")
    p_cfg_set.add_argument("value", help="New value")

    # estimate
    p_est = sub.add_parser("estimate", help="Estimate likely cost of an upcoming task")
    p_est.add_argument("--model", default="claude-opus-4-8", help="Model to estimate for")
    p_est.add_argument("--task-type", dest="task_type",
                       help="read_only_qa|plan|code_edit|refactor_wide|debug_run|research")
    p_est.add_argument("--prompt-tokens", dest="prompt_tokens", type=int,
                       help="Approx input/prompt token count (optional)")
    p_est.add_argument("--turns", type=int, help="Override expected number of turns")
    p_est.add_argument("--project", help="Project slug for saved estimate")
    p_est.add_argument("--save", action="store_true", help="Persist estimate metadata")

    # run (UI)
    p_run = sub.add_parser("run", help="Start the local web dashboard")
    p_run.add_argument("--host", default="127.0.0.1", help="Bind host (localhost only by default)")
    p_run.add_argument("--port", type=int, default=8787, help="Port (default 8787)")

    # import-account
    p_acct = sub.add_parser("import-account",
                            help="Manually import an official account/billing export (CSV/JSON)")
    p_acct.add_argument("--file", required=True, metavar="PATH")
    p_acct.add_argument("--verbose", "-v", action="store_true")

    # doctor
    sub.add_parser("doctor", help="Diagnose config, pricing, DB, and Claude Code integration")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    dispatch = {
        "init": cmd_init,
        "import": cmd_import,
        "log": cmd_log,
        "status": cmd_status,
        "report": cmd_report,
        "config": cmd_config,
        "estimate": cmd_estimate,
        "run": cmd_run,
        "import-account": cmd_import_account,
        "doctor": cmd_doctor,
    }

    handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        return 1

    # Ensure UTF-8 output on Windows (for status line characters)
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf-16"):
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if sys.stderr.encoding and sys.stderr.encoding.lower() not in ("utf-8", "utf-16"):
        import io
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    try:
        return handler(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"[tc] Unexpected error: {exc}", file=sys.stderr)
        if os.environ.get("TC_DEBUG"):
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
