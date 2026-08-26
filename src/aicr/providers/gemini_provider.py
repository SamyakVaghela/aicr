from __future__ import annotations

import os
from typing import Any, Dict

from .base import ConfigError, Provider, http_json


class GeminiProvider(Provider):
    """Google Gemini API.

    PRIVACY WARNING: on Gemini's **free tier**, Google states that prompts and
    responses are used to improve their products. That means your source code.
    Enable billing on the API key before pointing this at a company codebase —
    the paid tier flips that to "not used". At roughly a cent per review the
    paid tier costs a few dollars a month for a whole team, so there is very
    little reason to run company code through the free tier.
    """

    name = "gemini"

    def __init__(self, cfg: Dict[str, Any]):
        super().__init__(cfg)
        self.model = self.model or "gemini-3.5-flash-lite"
        self.base_url = str(
            cfg.get("base_url") or "https://generativelanguage.googleapis.com/v1beta"
        ).rstrip("/")
        self.key_env = str(cfg.get("api_key_env") or "GEMINI_API_KEY")
        self.api_key = cfg.get("api_key") or os.environ.get(self.key_env, "")

    def complete(self, system: str, user: str) -> str:
        if not self.api_key:
            raise ConfigError(
                f"{self.key_env} is not set. Create a key at "
                f"https://aistudio.google.com/apikey and export it, e.g.\n"
                f"  echo 'export {self.key_env}=...' >> ~/.zshrc && source ~/.zshrc\n"
                f"  Enable billing on the key so your code is not used for training."
            )
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": self.max_tokens,
                "responseMimeType": "application/json",
            },
        }
        data = http_json(
            f"{self.base_url}/models/{self.model}:generateContent",
            payload,
            {"x-goog-api-key": self.api_key},
            timeout=self.timeout,
        )

        candidates = data.get("candidates") or []
        if not candidates:
            blocked = (data.get("promptFeedback") or {}).get("blockReason")
            if blocked:
                raise ConfigError(
                    f"Gemini refused the request (blockReason={blocked}). "
                    "Safety filters sometimes trip on security-related code; "
                    "try a different model or provider for this diff."
                )
            return ""

        parts = (candidates[0].get("content") or {}).get("parts") or []
        return "".join(p.get("text", "") for p in parts if isinstance(p, dict))
