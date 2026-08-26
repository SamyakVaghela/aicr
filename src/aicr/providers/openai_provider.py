from __future__ import annotations

import os
from typing import Any, Dict

from .base import ConfigError, Provider, http_json


class OpenAIProvider(Provider):
    """Works with the OpenAI API and any OpenAI-compatible endpoint
    (Azure-style gateways, OpenRouter, vLLM, LiteLLM...) via `base_url`."""

    name = "openai"

    def __init__(self, cfg: Dict[str, Any]):
        super().__init__(cfg)
        self.model = self.model or "gpt-4.1"
        self.base_url = str(cfg.get("base_url") or "https://api.openai.com/v1").rstrip("/")
        self.key_env = str(cfg.get("api_key_env") or "OPENAI_API_KEY")
        self.api_key = cfg.get("api_key") or os.environ.get(self.key_env, "")

    def complete(self, system: str, user: str) -> str:
        if not self.api_key:
            raise ConfigError(
                f"{self.key_env} is not set. Export your OpenAI API key, e.g.\n"
                f"  echo 'export {self.key_env}=sk-...' >> ~/.zshrc && source ~/.zshrc"
            )
        payload = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
        }
        data = http_json(
            f"{self.base_url}/chat/completions",
            payload,
            {"Authorization": f"Bearer {self.api_key}"},
            timeout=self.timeout,
        )
        choices = data.get("choices") or []
        if not choices:
            return ""
        return (choices[0].get("message") or {}).get("content") or ""
