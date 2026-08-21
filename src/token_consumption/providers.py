"""
Provider registry: built-in AI tool/provider cards (code-defined) merged with
user-added custom providers (DB-backed). Connection methods describe SAFE
methods only — env_var (reference only, never a stored value), manual_import
(user-downloaded export file), manual_entry (typed plan/price). No provider
in this registry is ever scraped, logged into, or has its cookies/session
tokens read.
"""

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

from . import db as db_mod


@dataclass
class ProviderCard:
    provider_key: str
    display_name: str
    category: str
    website: str
    connection_methods: list[str]
    env_var_names: list[str]
    limitations: str
    setup_note: str = ""
    is_custom: bool = False


BUILTIN_PROVIDERS: dict[str, ProviderCard] = {
    "anthropic": ProviderCard(
        provider_key="anthropic", display_name="Claude / Anthropic", category="assistant",
        website="https://www.anthropic.com",
        connection_methods=["env_var", "manual_import", "manual_entry"],
        env_var_names=["ANTHROPIC_ADMIN_API_KEY", "ANTHROPIC_ORG_ID", "ANTHROPIC_WORKSPACE_ID"],
        limitations=("Admin API requires a Console organization — unavailable for personal "
                    "Pro/Max accounts. Use manual import/entry instead."),
        setup_note=("Already integrated — see /account for the full Admin API + manual "
                    "import + reconciliation flows (docs/ANTHROPIC_API_SETUP.md)."),
    ),
    "openai": ProviderCard(
        provider_key="openai", display_name="OpenAI / ChatGPT / Codex", category="assistant",
        website="https://platform.openai.com",
        connection_methods=["manual_import", "manual_entry"],
        env_var_names=["OPENAI_API_KEY"],
        limitations=("No official per-user cost-report API for ChatGPT Plus/Pro subscriptions. "
                    "An org usage API exists for API-billing customers but is not wired up "
                    "this phase."),
        setup_note=("Export usage from platform.openai.com/usage (API billing) and import via "
                    "'tc import-account', or record your ChatGPT/Codex subscription manually."),
    ),
    "github_copilot": ProviderCard(
        provider_key="github_copilot", display_name="GitHub Copilot", category="coding_assistant",
        website="https://github.com/features/copilot",
        connection_methods=["manual_entry"],
        env_var_names=[],
        limitations="No public per-token cost API for individual seats. Flat plan pricing only.",
        setup_note="Record your Copilot plan and monthly price manually.",
    ),
    "google_gemini": ProviderCard(
        provider_key="google_gemini", display_name="Google Gemini", category="assistant",
        website="https://gemini.google.com",
        connection_methods=["manual_import", "manual_entry"],
        env_var_names=["GOOGLE_API_KEY", "GEMINI_API_KEY"],
        limitations=("Google AI Studio/Vertex billing export exists but is not wired up this "
                    "phase. Manual entry only for now."),
        setup_note="Record your Gemini plan manually, or import a billing export via 'tc import-account'.",
    ),
    "perplexity": ProviderCard(
        provider_key="perplexity", display_name="Perplexity", category="assistant",
        website="https://www.perplexity.ai",
        connection_methods=["manual_entry"],
        env_var_names=[],
        limitations="No documented usage/cost API for individual subscriptions.",
        setup_note="Record your Perplexity plan and monthly price manually.",
    ),
    "notion_ai": ProviderCard(
        provider_key="notion_ai", display_name="Notion AI", category="productivity_assistant",
        website="https://www.notion.so/product/ai",
        connection_methods=["manual_entry"],
        env_var_names=[],
        limitations="No documented usage/cost API. Billed as a workspace add-on.",
        setup_note="Record your Notion AI add-on price manually.",
    ),
}


def _row_to_card(row) -> ProviderCard:
    return ProviderCard(
        provider_key=row["provider_key"], display_name=row["display_name"],
        category=row["category"] or "custom", website=row["website"] or "",
        connection_methods=json.loads(row["connection_methods"] or "[]"),
        env_var_names=json.loads(row["env_var_names"] or "[]"),
        limitations=row["limitations"] or "", setup_note="", is_custom=True,
    )


def list_providers() -> list[dict]:
    """Built-in providers merged with custom (DB) providers. Built-in keys win on clash."""
    out = {k: asdict(v) for k, v in BUILTIN_PROVIDERS.items()}
    with db_mod.connection() as con:
        for row in db_mod.get_custom_providers(con):
            if row["provider_key"] not in out:
                out[row["provider_key"]] = asdict(_row_to_card(row))
    return sorted(out.values(), key=lambda p: p["display_name"])


def get_provider(key: str) -> dict | None:
    for p in list_providers():
        if p["provider_key"] == key:
            return p
    return None


def add_custom_provider(
    provider_key: str,
    display_name: str,
    category: str | None = None,
    website: str | None = None,
    connection_methods: list[str] | None = None,
    env_var_names: list[str] | None = None,
    limitations: str | None = None,
) -> bool:
    """Add a custom provider. Raises ValueError if provider_key clashes with a built-in."""
    if provider_key in BUILTIN_PROVIDERS:
        raise ValueError(f"{provider_key!r} is a built-in provider key; choose a different key.")
    row = {
        "provider_key": provider_key,
        "display_name": display_name,
        "category": category or "custom",
        "website": website or "",
        "connection_methods": json.dumps(connection_methods or ["manual_entry"]),
        "env_var_names": json.dumps(env_var_names or []),
        "limitations": limitations or "",
        "is_custom": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with db_mod.connection() as con:
        return db_mod.insert_provider(con, row)


def provider_status(key: str) -> str:
    """
    Coarse status for a provider:
      connected   — a referenced env var is set in this environment
      manual      — no env var, but at least one account is manually configured
      unconfigured — a safe connection method exists but nothing is set up yet
      unsupported — no safe connection method is available at all
      unknown     — provider key not found
    """
    provider = get_provider(key)
    if provider is None:
        return "unknown"
    for var in provider["env_var_names"]:
        if os.environ.get(var):
            return "connected"
    from . import accounts as accounts_mod
    if any(a["provider_key"] == key for a in accounts_mod.list_accounts()):
        return "manual"
    if provider["connection_methods"]:
        return "unconfigured"
    return "unsupported"
