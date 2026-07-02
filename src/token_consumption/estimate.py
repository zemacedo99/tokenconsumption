"""
Preventive cost estimator (v1).

Estimates the likely cost of an upcoming task BEFORE doing expensive work,
using your own local history (average cost per turn for the model) plus a
per-task-type turn multiplier. No external AI; pure local statistics.

Confidence scales with how many historical samples exist. With little history,
estimates are inflated (conservative) so the tool errs toward asking.
"""

import uuid as _uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

from . import config as cfg_mod
from . import db as db_mod
from . import pricing as pricing_mod


# Fallback per-task-type profile if task_types.yaml is unavailable.
_DEFAULT_TASK_PROFILE = {
    "read_only_qa":  {"expected_turns": 1,  "expected_output_tokens": 800},
    "plan":          {"expected_turns": 3,  "expected_output_tokens": 2000},
    "code_edit":     {"expected_turns": 5,  "expected_output_tokens": 1500},
    "refactor_wide": {"expected_turns": 15, "expected_output_tokens": 4000},
    "debug_run":     {"expected_turns": 8,  "expected_output_tokens": 2500},
    "research":      {"expected_turns": 10, "expected_output_tokens": 3000},
    "unknown":       {"expected_turns": 5,  "expected_output_tokens": 2000},
}


@dataclass
class Estimate:
    model: str
    task_type: str
    est_turns: int
    est_input_tokens: int
    est_output_tokens: int
    est_cache_read_tokens: int
    est_cost_usd: float | None
    est_cost_eur: float | None
    confidence: str            # low | medium | high
    samples: int
    threshold_value: float
    threshold_currency: str
    warn_at_pct: float
    recommendation: str        # proceed | warn | ask
    cheaper_model: str | None
    notes: list[str]


def _task_profile(task_type: str | None) -> dict:
    """Load per-task-type profile from task_types.yaml with fallback defaults."""
    tt = task_type or "unknown"
    profiles = dict(_DEFAULT_TASK_PROFILE)
    yaml_path = cfg_mod._config_dir() / "task_types.yaml"
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        for entry in (data or {}).get("task_types", []):
            name = entry.get("name")
            if name:
                profiles.setdefault(name, {})
                profiles[name] = {
                    "expected_turns": profiles.get(name, {}).get("expected_turns", 5),
                    "expected_output_tokens": entry.get("expected_output_tokens", 2000),
                }
        default = (data or {}).get("default", {})
        if default:
            profiles["unknown"] = {
                "expected_turns": _DEFAULT_TASK_PROFILE["unknown"]["expected_turns"],
                "expected_output_tokens": default.get("expected_output_tokens", 2000),
            }
    except Exception:
        pass
    return profiles.get(tt, profiles["unknown"])


def _model_turn_stats(con, model: str) -> dict:
    """Average cost/tokens per ASSISTANT turn for a model, from local history."""
    row = con.execute("""
        SELECT
            COUNT(*)                  AS n,
            AVG(cost_total)           AS avg_cost,
            AVG(input_tokens)         AS avg_in,
            AVG(output_tokens)        AS avg_out,
            AVG(cache_read_tokens)    AS avg_cache_read
        FROM turns
        WHERE role='assistant' AND model=? AND cost_total IS NOT NULL
    """, (model,)).fetchone()
    return {
        "n": row["n"] or 0,
        "avg_cost": row["avg_cost"],
        "avg_in": row["avg_in"] or 0,
        "avg_out": row["avg_out"] or 0,
        "avg_cache_read": row["avg_cache_read"] or 0,
    }


def _confidence(samples: int) -> str:
    if samples >= 20:
        return "high"
    if samples >= 5:
        return "medium"
    return "low"


def _recommend(est_eur: float | None, threshold: float, warn_pct: float,
               cfg: dict, is_unpriced: bool) -> tuple[str, str | None, list[str]]:
    """Return (recommendation, cheaper_model, notes)."""
    notes: list[str] = []
    cheaper = None
    if is_unpriced or est_eur is None:
        notes.append("Model is unpriced — cost cannot be computed. Fill config/pricing.json.")
        return "warn", cfg.get("cheaper_model_suggestion"), notes

    warn_threshold = threshold * (warn_pct / 100.0)
    if cfg.get("recommend_cheaper_model_above_threshold", True):
        cheaper = cfg.get("cheaper_model_suggestion")

    if est_eur > threshold:
        notes.append(f"Estimate €{est_eur:.2f} EXCEEDS threshold €{threshold:.2f}. "
                     "Ask for confirmation; consider a cheaper model or narrower scope.")
        return "ask", cheaper, notes
    if est_eur >= warn_threshold:
        notes.append(f"Estimate €{est_eur:.2f} is near threshold (warn at €{warn_threshold:.2f}). "
                     "Consider reducing scope or splitting into phases.")
        return "warn", cheaper, notes
    notes.append(f"Estimate €{est_eur:.2f} is below threshold €{threshold:.2f}. Safe to proceed.")
    return "proceed", None, notes


def estimate(
    model: str,
    task_type: str | None = None,
    prompt_tokens: int | None = None,
    turns: int | None = None,
    db_path: Path | None = None,
) -> Estimate:
    cfg = cfg_mod.load()
    threshold = float(cfg.get("safety_threshold_value", 20))
    warn_pct = float(cfg.get("warn_at_percentage_of_threshold", 70))
    profile = _task_profile(task_type)
    est_turns = turns or profile["expected_turns"]

    table = pricing_mod.get_table()
    is_unpriced = not table.is_known(model)

    notes: list[str] = []
    samples = 0
    est_in = est_out = est_cache_read = 0
    est_usd: float | None = None

    db_path = db_path or db_mod._db_path()
    if db_path.exists():
        with db_mod.connection(db_path) as con:
            stats = _model_turn_stats(con, model)
            samples = stats["n"]
            if samples > 0:
                est_in = int(round(stats["avg_in"] * est_turns))
                est_out = int(round(stats["avg_out"] * est_turns))
                est_cache_read = int(round(stats["avg_cache_read"] * est_turns))
                if stats["avg_cost"] is not None:
                    est_usd = stats["avg_cost"] * est_turns

    # Fallback: no history — build from task-type token expectation + pricing.
    if est_usd is None and not is_unpriced:
        est_in = prompt_tokens or 8000
        est_out = profile["expected_output_tokens"] * est_turns
        cost = table.compute_cost(model, input_tokens=est_in, output_tokens=est_out)
        est_usd = cost.total_cost
        notes.append("No local history for this model — using conservative token defaults.")

    confidence = _confidence(samples)

    est_eur: float | None = None
    if est_usd is not None:
        est_eur = cfg_mod.fx_to_eur(est_usd, cfg)
        # Conservative inflation when confidence is low.
        if confidence == "low":
            est_eur *= 1.5
            est_usd *= 1.5
            notes.append("Low confidence — estimate inflated 1.5x to stay conservative.")

    recommendation, cheaper, rec_notes = _recommend(est_eur, threshold, warn_pct, cfg, is_unpriced)
    notes.extend(rec_notes)

    return Estimate(
        model=model,
        task_type=task_type or "unknown",
        est_turns=est_turns,
        est_input_tokens=est_in,
        est_output_tokens=est_out,
        est_cache_read_tokens=est_cache_read,
        est_cost_usd=est_usd,
        est_cost_eur=est_eur,
        confidence=confidence,
        samples=samples,
        threshold_value=threshold,
        threshold_currency=cfg.get("safety_threshold_currency", "EUR"),
        warn_at_pct=warn_pct,
        recommendation=recommendation,
        cheaper_model=cheaper,
        notes=notes,
    )


def save_estimate(est: Estimate, session_id: str | None = None,
                  project_slug: str | None = None, db_path: Path | None = None) -> str:
    """Persist estimate metadata (no prompt text). Returns the estimate_uuid."""
    cfg = cfg_mod.load()
    est_uuid = str(_uuid.uuid4())
    ts = datetime.now(timezone.utc).isoformat()
    with db_mod.connection(db_path) as con:
        con.execute("""
            INSERT INTO estimates (
                estimate_uuid, ts, session_id, model, task_type, project_slug,
                est_input_tokens, est_output_tokens, est_cache_read_tokens,
                est_cost, est_currency, confidence,
                threshold_at_time, threshold_currency,
                confirmation_required, cheaper_model_recommended
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            est_uuid, ts, session_id or "", est.model, est.task_type, project_slug,
            est.est_input_tokens, est.est_output_tokens, est.est_cache_read_tokens,
            est.est_cost_eur, est.threshold_currency, est.confidence,
            est.threshold_value, est.threshold_currency,
            1 if est.recommendation == "ask" else 0,
            est.cheaper_model,
        ))
    return est_uuid


def format_estimate(est: Estimate) -> str:
    """Human-readable multi-line estimate for the CLI."""
    cost_str = f"€{est.est_cost_eur:.2f}" if est.est_cost_eur is not None else "unknown (unpriced)"
    lines = [
        f"Budget estimate: likely ≈ {cost_str}, threshold €{est.threshold_value:.2f}, "
        f"model: {est.model}, confidence: {est.confidence}",
        f"  task_type={est.task_type}  est_turns={est.est_turns}  "
        f"samples={est.samples}  recommendation={est.recommendation.upper()}",
    ]
    if est.cheaper_model and est.recommendation in ("ask", "warn"):
        lines.append(f"  suggested cheaper model: {est.cheaper_model}")
    for n in est.notes:
        lines.append(f"  - {n}")
    return "\n".join(lines)
