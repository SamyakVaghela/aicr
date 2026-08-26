"""Configuration loading.

Resolution order (later overrides earlier):
  1. built-in defaults
  2. ~/.config/aicr/config.toml          (per-developer machine defaults)
  3. <repo-root>/.aicr.toml              (team settings, committed)
  4. <repo-root>/.aicr.local.toml        (per-developer overrides, gitignored)
  5. AICR_* environment variables
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

try:  # py3.11+
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover
    try:
        import tomli as _toml  # type: ignore
    except ModuleNotFoundError:
        _toml = None  # type: ignore

DEFAULTS: Dict[str, Any] = {
    "provider": "anthropic",
    "fail_on": "high",          # block push at this severity and above
    "fail_open": True,           # if the provider errors, allow the push
    "max_files": 60,
    "max_diff_bytes": 400_000,
    "chunk_bytes": 45_000,
    "context_lines": 5,
    "concurrency": 4,
    "timeout_s": 120,
    "cache": True,
    # Where to drop a markdown report when a push is blocked, so GUI git
    # clients (which hide hook output) still show the developer something.
    "report_path": ".aicr-review.md",
    "include_full_file_under_bytes": 12_000,
    "exclude": [
        "*.lock", "*.min.js", "*.min.css", "*.map", "*.svg", "*.png", "*.jpg",
        "*.jpeg", "*.gif", "*.ico", "*.pdf", "*.zip", "*.gz", "*.jar", "*.woff*",
        "*.mp4", "*.mov", "*.parquet", "*.csv", "*.ipynb_checkpoints/*",
        "node_modules/*", "vendor/*", "dist/*", "build/*", "*.pb.go",
        "*_pb2.py", "package-lock.json", "yarn.lock", "poetry.lock",
        "pnpm-lock.yaml", "Pipfile.lock", "go.sum", "*.snap",
    ],
    "project_context": "",
    "custom_rules": [],
    # Opt-in visibility for a manager/admin: off by default. See docs/ROLLOUT.md
    # "Visibility for admins" for what this can and cannot tell you.
    "telemetry": {
        "enabled": False,
        "webhook_url": "",
        "include_findings": False,
        "timeout_s": 4,
        # "json" (default) sends aicr's own event shape — works with anything
        # that accepts a webhook, including a Parse JSON step in Power
        # Automate. "card" sends a ready-to-render Microsoft Adaptive Card
        # instead, for Teams setups whose only available action is
        # "Post card in a chat or channel" (which requires its input to
        # already be a valid card — see telemetry.py:_adaptive_card).
        "format": "json",
    },
    "anthropic": {
        "model": "claude-sonnet-5",
        "api_key_env": "ANTHROPIC_API_KEY",
        "base_url": "https://api.anthropic.com",
        "max_tokens": 8000,
    },
    "openai": {
        "model": "gpt-4.1",
        "api_key_env": "OPENAI_API_KEY",
        "base_url": "https://api.openai.com/v1",
        "max_tokens": 8000,
    },
    "gemini": {
        # Cheapest sensible default. Use a Flash model for more thorough reviews.
        # IMPORTANT: enable billing on the key — Gemini's FREE tier uses your
        # prompts (i.e. your source code) to improve Google's products.
        "model": "gemini-3.5-flash-lite",
        "api_key_env": "GEMINI_API_KEY",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "max_tokens": 8000,
    },
    "ollama": {
        "model": "qwen2.5-coder:14b",
        "base_url": "http://localhost:11434",
        "max_tokens": 8000,
    },
}

_ENV_MAP = {
    "AICR_PROVIDER": ("provider", str),
    "AICR_FAIL_ON": ("fail_on", str),
    "AICR_FAIL_OPEN": ("fail_open", "bool"),
    "AICR_MODEL": ("_model_override", str),
    "AICR_CONCURRENCY": ("concurrency", int),
    "AICR_TIMEOUT": ("timeout_s", int),
    "AICR_CACHE": ("cache", "bool"),
    "AICR_MAX_FILES": ("max_files", int),
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _read_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text)
    if _toml is None:
        raise RuntimeError(
            f"Cannot parse {path}: install tomli (`pip install tomli`) or use Python 3.11+."
        )
    return _toml.loads(text)


def _as_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on")


class Config:
    def __init__(self, data: Dict[str, Any], sources: Optional[list] = None):
        self.data = data
        self.sources = sources or []

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    @property
    def provider(self) -> str:
        return str(self.data.get("provider", "anthropic")).lower()

    def provider_config(self) -> Dict[str, Any]:
        pc = dict(self.data.get(self.provider) or {})
        if self.data.get("_model_override"):
            pc["model"] = self.data["_model_override"]
        pc.setdefault("max_tokens", 8000)
        pc["timeout_s"] = self.data.get("timeout_s", 120)
        return pc

    def to_dict(self) -> Dict[str, Any]:
        return copy.deepcopy(self.data)


def user_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "aicr" / "config.toml"


def load_config(repo_root: Optional[Path] = None) -> Config:
    data = copy.deepcopy(DEFAULTS)
    sources = []

    candidates = [user_config_path()]
    if repo_root:
        candidates += [
            repo_root / ".aicr.toml",
            repo_root / ".aicr.json",
            repo_root / ".aicr.local.toml",
        ]

    for path in candidates:
        try:
            chunk = _read_file(path)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Failed to read config {path}: {exc}") from exc
        if chunk:
            data = _deep_merge(data, chunk)
            sources.append(str(path))

    for env_key, (cfg_key, kind) in _ENV_MAP.items():
        raw = os.environ.get(env_key)
        if raw is None or raw == "":
            continue
        if kind == "bool":
            data[cfg_key] = _as_bool(raw)
        elif kind is int:
            try:
                data[cfg_key] = int(raw)
            except ValueError:
                pass
        else:
            data[cfg_key] = raw
        sources.append(f"env:{env_key}")

    # Webhook URLs are bearer credentials in disguise — keep them out of a
    # committed .aicr.toml by letting the env var win, same as api_key_env.
    webhook = os.environ.get("AICR_TELEMETRY_WEBHOOK")
    if webhook:
        data.setdefault("telemetry", {})["webhook_url"] = webhook
        data["telemetry"]["enabled"] = True
        sources.append("env:AICR_TELEMETRY_WEBHOOK")

    # Lets a quick `AICR_TELEMETRY_WEBHOOK=... AICR_TELEMETRY_FORMAT=card
    # aicr doctor --test-webhook` try the real destination without touching
    # .aicr.toml — which usually points somewhere else (a local test server,
    # a different team's webhook) and shouldn't be edited just to try this.
    fmt = os.environ.get("AICR_TELEMETRY_FORMAT")
    if fmt:
        data.setdefault("telemetry", {})["format"] = fmt
        sources.append("env:AICR_TELEMETRY_FORMAT")

    return Config(data, sources)


DEFAULT_TEAM_CONFIG = """\
# aicr — team code review settings. Commit this file.
# Per-developer overrides go in .aicr.local.toml (gitignored).

provider = "anthropic"     # anthropic | openai | ollama
fail_on  = "high"          # block push on this severity and above
fail_open = true           # allow push if the AI provider is unreachable
concurrency = 4
timeout_s = 120

# Short description of the codebase. Improves review quality a lot.
project_context = \"\"\"
Describe your stack here, e.g.:
Django 4 REST API + React frontend. Postgres. Deployed on AWS ECS.
All DB access must go through the repository layer in app/repositories/.
\"\"\"

# Team-specific rules the reviewer must enforce, in plain English.
custom_rules = [
  "No secrets, API keys, tokens, or passwords in source or config files.",
  "All new HTTP endpoints must validate and sanitize user input.",
  "No raw SQL string interpolation - use parameterized queries or the ORM.",
  "Database migrations must be backwards compatible with the running release.",
  "No console.log / print statements left in production code paths.",
  "New business logic needs at least one accompanying test.",
]

[anthropic]
model = "claude-sonnet-5"
api_key_env = "ANTHROPIC_API_KEY"

[openai]
model = "gpt-4.1"
api_key_env = "OPENAI_API_KEY"

[ollama]
model = "qwen2.5-coder:14b"
base_url = "http://localhost:11434"

# Optional: let a manager/admin see review activity across the team (counts and
# pass/fail only, not code — see docs/ROLLOUT.md "Visibility for admins").
# Prefer AICR_TELEMETRY_WEBHOOK in each developer's shell over committing a
# webhook URL here, since it behaves like a credential.
# [telemetry]
# enabled = true
# webhook_url = "https://hooks.slack.com/services/…"
"""
