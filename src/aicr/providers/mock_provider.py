"""Deterministic offline provider — used by tests and `AICR_PROVIDER=mock`.

Flags a few obvious patterns with plain regex so the whole pipeline
(hook -> diff -> chunk -> review -> report -> exit code) can be exercised
without a network call or an API key.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from .base import Provider

PATTERNS = [
    (r"(?i)\w*(api[_-]?key|secret|passwd|password|token)\w*\s*[:=]\s*[\"'][^\"']{8,}", "critical",
     "security", "Hardcoded credential", "A secret appears to be committed in source."),
    (r"(?i)eval\s*\(", "high", "security", "Use of eval()",
     "eval() on untrusted input allows arbitrary code execution."),
    (r"(?i)(execute|query)\s*\(\s*[f\"'].*(\+|%s*\{)", "high", "security",
     "Possible SQL injection", "SQL built via string interpolation."),
    (r"except\s*:\s*(#.*)?$", "medium", "reliability", "Bare except",
     "Bare `except:` swallows KeyboardInterrupt/SystemExit and hides bugs."),
    (r"(?i)console\.log\(|^\s*print\(", "low", "maintainability", "Debug statement left in code",
     "Remove debug output or switch to the logger."),
]


class MockProvider(Provider):
    name = "mock"

    def __init__(self, cfg):
        super().__init__(cfg)
        self.model = self.model or "regex-rules"

    def complete(self, system: str, user: str) -> str:  # noqa: ARG002
        findings: List[Dict[str, Any]] = []
        current_file = "unknown"
        for raw in user.splitlines():
            m = re.match(r"^===\s*FILE:\s*(.+?)\s*===", raw)
            if m:
                current_file = m.group(1)
                continue
            numbered = re.match(r"^\s*\d+ \| (.*)$", raw)  # whole-file mode
            if numbered:
                line = numbered.group(1)
            elif raw.startswith("+") and not raw.startswith("+++"):
                line = raw[1:]
            else:
                continue
            for pat, sev, cat, title, detail in PATTERNS:
                if re.search(pat, line):
                    findings.append({
                        "file": current_file,
                        "line": None,
                        "severity": sev,
                        "category": cat,
                        "title": title,
                        "detail": detail,
                        "suggestion": "",
                        "confidence": "high",
                    })
                    break
        return json.dumps({
            "summary": f"Mock review found {len(findings)} issue(s).",
            "findings": findings,
        })

    def healthcheck(self) -> str:
        return "OK (mock)"
