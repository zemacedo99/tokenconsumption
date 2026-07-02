"""
Ingest Claude Code JSONL transcripts into the local SQLite database.

Privacy: only metadata and usage blocks are stored. Message text, file
contents, tool inputs/outputs, and diffs are never saved by default.
"""

import json
import re
import uuid as _uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from . import config as cfg_mod
from . import db as db_mod
from . import pricing as pricing_mod


# ── Transcript discovery ──────────────────────────────────────────────────────

def _claude_projects_root() -> Path:
    """~/.claude/projects/"""
    return Path.home() / ".claude" / "projects"


def _iter_transcript_files(projects_root: Path | None = None) -> Generator[tuple[str, Path], None, None]:
    """Yield (project_slug, .jsonl path) for all local transcripts."""
    root = projects_root or _claude_projects_root()
    if not root.exists():
        return
    for project_dir in root.iterdir():
        if not project_dir.is_dir():
            continue
        slug = _decode_project_slug(project_dir.name)
        for jsonl_file in project_dir.glob("*.jsonl"):
            yield slug, jsonl_file


def _decode_project_slug(encoded: str) -> str:
    """
    Convert Claude Code's encoded dir name back to a readable repo name.
    Claude Code encodes the CWD path by replacing path separators with '--'.
    We extract just the last segment as the project slug.
    """
    # e.g. "C--Users-alice-Git-MyRepo" → "MyRepo"
    parts = encoded.replace("--", "/").split("/")
    return parts[-1] if parts else encoded


def _cwd_from_encoded(encoded: str) -> str:
    """Best-effort reconstruct a readable path from the encoded project dir name."""
    # C--Users-foo-Git-Repo  →  C:/Users/foo/Git/Repo
    if "--" in encoded:
        drive, rest = encoded.split("--", 1)
        return f"{drive}:/{rest.replace('-', '/')}"
    return encoded


# ── JSONL parsing ─────────────────────────────────────────────────────────────

def _parse_line(line: str) -> dict | None:
    """Parse one JSONL line. Return None on error or empty."""
    line = line.strip()
    if not line:
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def _extract_turn(
    record: dict,
    project_slug: str,
    cwd: str,
    account_profile: str,
) -> dict | None:
    """
    Extract a DB-ready turn dict from a raw JSONL record.
    Returns None for lines that aren't turn records (e.g. queue-operation).
    Only stores metadata — never stores message content.
    """
    rec_type = record.get("type", "")

    # We want 'assistant' turn records that carry a usage block.
    # User turns have no usage; we skip them.
    if rec_type not in ("assistant", "user"):
        return None

    msg = record.get("message", {})
    if not isinstance(msg, dict):
        return None

    usage = msg.get("usage") or record.get("usage")
    role = msg.get("role") or record.get("role") or rec_type

    # Derive a stable UUID for this record
    turn_uuid = (
        record.get("uuid")
        or record.get("id")
        or msg.get("id")
    )
    if not turn_uuid:
        return None  # can't deduplicate without an id

    ts = record.get("timestamp") or record.get("ts") or msg.get("created_at", "")
    model = msg.get("model") or record.get("model")
    session_id = record.get("sessionId") or record.get("session_id", "")
    parent_uuid = record.get("parentUuid") or record.get("parent_uuid")

    turn = {
        "turn_uuid": turn_uuid,
        "session_id": session_id,
        "parent_uuid": parent_uuid,
        "ts": ts,
        "account_profile": account_profile,
        "cwd": cwd,
        "project_slug": project_slug,
        "role": role,
        "model": model,
        "task_type": None,
        "input_tokens": None,
        "output_tokens": None,
        "cache_read_tokens": None,
        "cache_write_5m_tokens": None,
        "cache_write_1h_tokens": None,
        "total_tokens": None,
        "cost_input": None,
        "cost_output": None,
        "cost_cache_read": None,
        "cost_cache_write": None,
        "cost_total": None,
        "cost_currency": "USD",
        "cost_source": "jsonl_local_pricing",
        "pricing_version": None,
    }

    if usage and isinstance(usage, dict):
        inp = usage.get("input_tokens", 0)
        out = usage.get("output_tokens", 0)
        cache_read = usage.get("cache_read_input_tokens", 0)
        cache_creation = usage.get("cache_creation", {})
        cache_write_5m = cache_creation.get("ephemeral_5m_input_tokens", 0) if isinstance(cache_creation, dict) else 0
        cache_write_1h = cache_creation.get("ephemeral_1h_input_tokens", 0) if isinstance(cache_creation, dict) else 0

        turn["input_tokens"] = inp
        turn["output_tokens"] = out
        turn["cache_read_tokens"] = cache_read
        turn["cache_write_5m_tokens"] = cache_write_5m
        turn["cache_write_1h_tokens"] = cache_write_1h
        turn["total_tokens"] = inp + out + cache_read + cache_write_5m + cache_write_1h

        if model:
            try:
                cost = pricing_mod.compute_cost(model, usage)
                turn["cost_input"] = cost.input_cost
                turn["cost_output"] = cost.output_cost
                turn["cost_cache_read"] = cost.cache_read_cost
                turn["cost_cache_write"] = cost.cache_write_cost
                turn["cost_total"] = cost.total_cost
                turn["cost_currency"] = cost.currency
                turn["pricing_version"] = cost.pricing_version
            except Exception:
                pass  # leave costs as None — unpriced

    return turn


# ── Upsert ────────────────────────────────────────────────────────────────────

_UPSERT_SQL = """
INSERT INTO turns (
    turn_uuid, session_id, parent_uuid, ts, account_profile, cwd,
    project_slug, role, model, task_type,
    input_tokens, output_tokens, cache_read_tokens,
    cache_write_5m_tokens, cache_write_1h_tokens, total_tokens,
    cost_input, cost_output, cost_cache_read, cost_cache_write,
    cost_total, cost_currency, cost_source, pricing_version
) VALUES (
    :turn_uuid, :session_id, :parent_uuid, :ts, :account_profile, :cwd,
    :project_slug, :role, :model, :task_type,
    :input_tokens, :output_tokens, :cache_read_tokens,
    :cache_write_5m_tokens, :cache_write_1h_tokens, :total_tokens,
    :cost_input, :cost_output, :cost_cache_read, :cost_cache_write,
    :cost_total, :cost_currency, :cost_source, :pricing_version
)
ON CONFLICT(turn_uuid) DO UPDATE SET
    cost_input=excluded.cost_input,
    cost_output=excluded.cost_output,
    cost_cache_read=excluded.cost_cache_read,
    cost_cache_write=excluded.cost_cache_write,
    cost_total=excluded.cost_total,
    pricing_version=excluded.pricing_version
"""


# ── Public API ────────────────────────────────────────────────────────────────

def ingest_file(
    jsonl_path: Path,
    project_slug: str,
    cwd: str,
    account_profile: str,
    db_path: Path | None = None,
    since_ts: str | None = None,
    verbose: bool = False,
) -> dict:
    """
    Ingest a single transcript file. Idempotent.
    Returns {"ingested": N, "skipped": M, "errors": K}.
    """
    db_mod.init_db(db_path)
    stats = {"ingested": 0, "skipped": 0, "errors": 0}
    affected_days: set[str] = set()

    with db_mod.connection(db_path) as con:
        try:
            lines = jsonl_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            if verbose:
                print(f"[tc:ingest] Cannot read {jsonl_path}: {exc}")
            stats["errors"] += 1
            return stats

        for line in lines:
            record = _parse_line(line)
            if record is None:
                continue

            turn = _extract_turn(record, project_slug, cwd, account_profile)
            if turn is None:
                stats["skipped"] += 1
                continue

            if since_ts and turn["ts"] and turn["ts"] < since_ts:
                stats["skipped"] += 1
                continue

            try:
                con.execute(_UPSERT_SQL, turn)
                stats["ingested"] += 1
                if turn["ts"]:
                    affected_days.add(turn["ts"][:10])
            except Exception as exc:
                if verbose:
                    print(f"[tc:ingest] DB error for {turn.get('turn_uuid')}: {exc}")
                stats["errors"] += 1

        for day in affected_days:
            db_mod.recompute_agg_daily(con, day, account_profile)

    return stats


def ingest_all(
    project_filter: str | None = None,
    since_ts: str | None = None,
    db_path: Path | None = None,
    verbose: bool = False,
) -> dict:
    """
    Ingest all local Claude Code transcripts.
    project_filter: if given, only ingest projects whose slug contains this string.
    """
    cfg = cfg_mod.load()
    account_profile = cfg.get("account_profile_name", "default")
    totals = {"ingested": 0, "skipped": 0, "errors": 0, "files": 0}

    for project_slug, jsonl_path in _iter_transcript_files():
        if project_filter and project_filter.lower() not in project_slug.lower():
            continue
        cwd = _cwd_from_encoded(jsonl_path.parent.name)
        if verbose:
            print(f"[tc:ingest] {jsonl_path.name}  (project: {project_slug})")
        stats = ingest_file(
            jsonl_path, project_slug, cwd, account_profile,
            db_path=db_path, since_ts=since_ts, verbose=verbose,
        )
        totals["ingested"] += stats["ingested"]
        totals["skipped"] += stats["skipped"]
        totals["errors"] += stats["errors"]
        totals["files"] += 1

    return totals


def ingest_session(
    session_id: str,
    db_path: Path | None = None,
    verbose: bool = False,
) -> dict:
    """Ingest a specific session by ID. Used by the Stop hook."""
    cfg = cfg_mod.load()
    account_profile = cfg.get("account_profile_name", "default")
    totals = {"ingested": 0, "skipped": 0, "errors": 0, "files": 0}

    for project_slug, jsonl_path in _iter_transcript_files():
        if session_id not in jsonl_path.stem:
            # session transcript is named <session-uuid>.jsonl
            if jsonl_path.stem != session_id:
                continue
        cwd = _cwd_from_encoded(jsonl_path.parent.name)
        stats = ingest_file(
            jsonl_path, project_slug, cwd, account_profile,
            db_path=db_path, verbose=verbose,
        )
        totals["ingested"] += stats["ingested"]
        totals["skipped"] += stats["skipped"]
        totals["errors"] += stats["errors"]
        totals["files"] += 1
        break  # session IDs are unique

    return totals


def ingest_by_transcript_path(
    transcript_path: str | Path,
    db_path: Path | None = None,
    verbose: bool = False,
) -> dict:
    """
    Ingest a single transcript given its exact path.
    Used by Claude Code Stop/SessionEnd hooks, which pass `transcript_path`.
    Derives project_slug and cwd from the parent directory name.
    """
    path = Path(transcript_path)
    cfg = cfg_mod.load()
    account_profile = cfg.get("account_profile_name", "default")
    if not path.exists():
        return {"ingested": 0, "skipped": 0, "errors": 1, "files": 0}
    project_slug = _decode_project_slug(path.parent.name)
    cwd = _cwd_from_encoded(path.parent.name)
    stats = ingest_file(
        path, project_slug, cwd, account_profile,
        db_path=db_path, verbose=verbose,
    )
    stats["files"] = 1
    return stats
