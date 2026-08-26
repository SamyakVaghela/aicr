from __future__ import annotations

import os
from typing import Any, Dict

from .base import ConfigError, Provider, http_json


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, cfg: Dict[str, Any]):
        super().__init__(cfg)
        self.model = self.model or "claude-sonnet-5"
        self.base_url = str(cfg.get("base_url") or "https://api.anthropic.com").rstrip("/")
        self.key_env = str(cfg.get("api_key_env") or "ANTHROPIC_API_KEY")
        self.api_key = cfg.get("api_key") or os.environ.get(self.key_env, "")
        self.version = str(cfg.get("api_version") or "2023-06-01")

    def complete(self, system: str, user: str) -> str:
        if not self.api_key:
            raise ConfigError(
                f"{self.key_env} is not set. Export your Anthropic API key, e.g.\n"
                f"  echo 'export {self.key_env}=sk-ant-...' >> ~/.zshrc && source ~/.zshrc"
            )
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": 0,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        data = http_json(
            f"{self.base_url}/v1/messages",
            payload,
            {"x-api-key": self.api_key, "anthropic-version": self.version},
            timeout=self.timeout,
        )
        parts = [
            b.get("text", "")
            for b in data.get("content", [])
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        return "".join(parts)
