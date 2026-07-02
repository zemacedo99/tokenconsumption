"""Load, validate, and edit budget policy configuration."""

import json
import os
import shutil
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _tool_root() -> Path:
    """Root directory of the TokenConsumption tool (parent of src/)."""
    return Path(__file__).resolve().parent.parent.parent


def _config_dir() -> Path:
    return _tool_root() / "config"


def _example_policy_path() -> Path:
    return _config_dir() / "budget_policy.example.json"


def _local_policy_path() -> Path:
    return _config_dir() / "budget_policy.json"


def _pricing_path(cfg: dict | None = None) -> Path:
    if cfg and cfg.get("pricing_json_path"):
        return Path(cfg["pricing_json_path"])
    return _config_dir() / "pricing.json"


def _data_dir(cfg: dict | None = None) -> Path:
    if cfg and cfg.get("data_dir"):
        return Path(cfg["data_dir"])
    return _tool_root() / "data"


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

DEFAULTS: dict[str, Any] = {
    "version": 1,
    "monthly_budget_value": 1000,
    "monthly_budget_currency": "USD",
    "safety_threshold_value": 20,
    "safety_threshold_currency": "EUR",
    "warn_at_percentage_of_threshold": 70,
    "require_confirmation_above_threshold": True,
    "recommend_cheaper_model_above_threshold": True,
    "cheaper_model_suggestion": "claude-haiku-4-5-20251001",
    "default_estimation_confidence": "conservative",
    "account_profile_name": "default",
    "privacy_mode": "metadata_only",
    "fx_rates": {"USD_to_EUR": 0.92, "updated_at": "2026-01-01"},
    "data_dir": None,
    "pricing_json_path": None,
}


def load() -> dict[str, Any]:
    """
    Return merged config: DEFAULTS → example → local override.
    Keys starting with '_' are stripped (comments).
    """
    cfg = dict(DEFAULTS)

    for path in (_example_policy_path(), _local_policy_path()):
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                clean = {k: v for k, v in raw.items() if not k.startswith("_") and k != "$schema"}
                cfg.update(clean)
            except (json.JSONDecodeError, OSError) as exc:
                print(f"[tc:config] Warning: could not load {path}: {exc}")

    # Env var overrides: TC_SAFETY_THRESHOLD_VALUE, TC_MONTHLY_BUDGET_VALUE, etc.
    for key in ("safety_threshold_value", "monthly_budget_value", "safety_threshold_currency",
                "monthly_budget_currency", "account_profile_name", "privacy_mode"):
        env_key = f"TC_{key.upper()}"
        if val := os.environ.get(env_key):
            try:
                cfg[key] = type(DEFAULTS[key])(val)  # cast to same type as default
            except (ValueError, TypeError):
                cfg[key] = val

    return cfg


# ---------------------------------------------------------------------------
# Validate (optional — requires jsonschema)
# ---------------------------------------------------------------------------

def validate(cfg: dict) -> list[str]:
    """Return list of validation errors; empty list means valid."""
    schema_path = _config_dir() / "schemas" / "budget_policy.schema.json"
    if not schema_path.exists():
        return []
    try:
        import jsonschema  # type: ignore
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        errors = sorted(str(e.message) for e in jsonschema.Draft7Validator(schema).iter_errors(cfg))
        return errors
    except ImportError:
        return []  # jsonschema not installed — skip


# ---------------------------------------------------------------------------
# Get / Set
# ---------------------------------------------------------------------------

def get_value(key: str) -> tuple[Any, str]:
    """Return (value, source_label)."""
    cfg = load()
    if key not in cfg:
        raise KeyError(f"Unknown config key: {key!r}. Run 'tc config get' to list keys.")
    local = _local_policy_path()
    source = "local" if (local.exists() and key in _read_json(local)) else "default"
    return cfg[key], source


def set_value(key: str, raw_value: str) -> None:
    """Persist a single key to budget_policy.json. Creates file from example if absent."""
    if key.startswith("_") or key == "$schema":
        raise ValueError(f"Cannot set internal key: {key!r}")

    # Determine target type from defaults (or str if unknown)
    default = DEFAULTS.get(key)
    if isinstance(default, bool):
        if raw_value.lower() in ("true", "1", "yes"):
            value: Any = True
        elif raw_value.lower() in ("false", "0", "no"):
            value = False
        else:
            raise ValueError(f"Expected boolean for {key!r}, got: {raw_value!r}")
    elif isinstance(default, int):
        value = int(raw_value)
    elif isinstance(default, float):
        value = float(raw_value)
    elif isinstance(default, (dict, list)):
        value = json.loads(raw_value)
    else:
        value = raw_value

    local = _local_policy_path()
    if not local.exists():
        # Bootstrap from example or minimal file
        if _example_policy_path().exists():
            shutil.copy(_example_policy_path(), local)
            # Strip comment fields
            data = {k: v for k, v in _read_json(local).items()
                    if not k.startswith("_") and k != "$schema"}
        else:
            data = dict(DEFAULTS)
    else:
        data = _read_json(local)

    # Backup before write
    shutil.copy(local, local.with_suffix(".json.bak"))
    data[key] = value
    local.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Set {key} = {json.dumps(value)}  (saved to {local})")


def list_keys() -> dict[str, Any]:
    """Return current effective config for display."""
    return load()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def fx_to_eur(usd_amount: float, cfg: dict | None = None) -> float:
    """Convert USD to EUR using configured FX rate."""
    if cfg is None:
        cfg = load()
    rate = cfg.get("fx_rates", {}).get("USD_to_EUR", 0.92)
    return usd_amount * float(rate)
