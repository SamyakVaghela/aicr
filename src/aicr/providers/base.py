"""Provider interface plus a small stdlib-only JSON/HTTP helper."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class ProviderError(RuntimeError):
    """Raised when the LLM backend cannot produce a review."""


class ConfigError(ProviderError):
    """Raised when the provider is misconfigured (missing key, bad model...)."""


def http_json(
    url: str,
    payload: Dict[str, Any],
    headers: Dict[str, str],
    timeout: int = 120,
    retries: int = 2,
) -> Dict[str, Any]:
    """POST JSON, return parsed JSON. Retries on 429/5xx with backoff."""
    body = json.dumps(payload).encode("utf-8")
    hdrs = {"Content-Type": "application/json", **headers}
    last_err: Optional[Exception] = None

    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:600]
            except Exception:  # noqa: BLE001
                pass
            if exc.code in (401, 403):
                raise ConfigError(f"Auth failed ({exc.code}) for {url}: {detail}") from exc
            if exc.code == 404:
                raise ConfigError(f"Not found ({exc.code}) for {url}: {detail}") from exc
            last_err = ProviderError(f"HTTP {exc.code} from {url}: {detail}")
            if exc.code not in (408, 409, 429, 500, 502, 503, 504):
                raise last_err from exc
        except urllib.error.URLError as exc:
            last_err = ProviderError(f"Cannot reach {url}: {exc.reason}")
        except TimeoutError as exc:  # pragma: no cover
            last_err = ProviderError(f"Timed out after {timeout}s calling {url}")

        if attempt < retries:
            time.sleep(1.5 * (2 ** attempt))

    raise last_err or ProviderError(f"Request to {url} failed")


class Provider(ABC):
    """Every backend implements complete(system, user) -> raw text."""

    name = "base"

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.model = str(cfg.get("model") or "")
        self.max_tokens = int(cfg.get("max_tokens") or 8000)
        self.timeout = int(cfg.get("timeout_s") or 120)

    @abstractmethod
    def complete(self, system: str, user: str) -> str:
        """Return the model's raw text response."""

    def healthcheck(self) -> str:
        """Cheap round-trip used by `aicr doctor`. Returns a status string."""
        out = self.complete("Reply with exactly: OK", "ping")
        return out.strip()[:40] or "(empty response)"
