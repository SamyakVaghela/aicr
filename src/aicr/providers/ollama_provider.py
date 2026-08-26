from __future__ import annotations

from typing import Any, Dict

from .base import Provider, http_json


class OllamaProvider(Provider):
    """Fully local reviews. No code leaves the machine."""

    name = "ollama"

    def __init__(self, cfg: Dict[str, Any]):
        super().__init__(cfg)
        self.model = self.model or "qwen2.5-coder:14b"
        self.base_url = str(cfg.get("base_url") or "http://localhost:11434").rstrip("/")

    def complete(self, system: str, user: str) -> str:
        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0, "num_predict": self.max_tokens},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        data = http_json(
            f"{self.base_url}/api/chat", payload, {}, timeout=self.timeout, retries=1
        )
        return (data.get("message") or {}).get("content") or ""
