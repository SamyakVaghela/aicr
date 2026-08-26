"""Core data types shared across the reviewer."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

SEVERITY_ORDER = ["info", "low", "medium", "high", "critical"]


def severity_rank(sev: str) -> int:
    try:
        return SEVERITY_ORDER.index((sev or "info").strip().lower())
    except ValueError:
        return 0


CATEGORIES = [
    "security",
    "correctness",
    "performance",
    "reliability",
    "maintainability",
    "testing",
    "style",
    "docs",
]


@dataclass
class Finding:
    """A single issue reported by the model."""

    file: str
    severity: str
    category: str
    title: str
    detail: str
    line: Optional[int] = None
    suggestion: str = ""
    confidence: str = "medium"

    def normalized(self) -> "Finding":
        sev = (self.severity or "info").strip().lower()
        if sev not in SEVERITY_ORDER:
            sev = "medium"
        cat = (self.category or "correctness").strip().lower()
        if cat not in CATEGORIES:
            cat = "correctness"
        conf = (self.confidence or "medium").strip().lower()
        if conf not in ("low", "medium", "high"):
            conf = "medium"
        line = self.line
        if isinstance(line, str):
            line = int(line) if line.strip().isdigit() else None
        return Finding(
            file=(self.file or "unknown").strip(),
            severity=sev,
            category=cat,
            title=(self.title or "Issue").strip(),
            detail=(self.detail or "").strip(),
            line=line,
            suggestion=(self.suggestion or "").strip(),
            confidence=conf,
        )

    @property
    def rank(self) -> int:
        return severity_rank(self.severity)

    def fingerprint(self) -> str:
        raw = f"{self.file}|{self.line}|{self.title.lower()}"
        return hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()[:12]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any], default_file: str = "unknown") -> "Finding":
        return Finding(
            file=str(d.get("file") or default_file),
            severity=str(d.get("severity") or "medium"),
            category=str(d.get("category") or "correctness"),
            title=str(d.get("title") or d.get("issue") or "Issue"),
            detail=str(d.get("detail") or d.get("description") or ""),
            line=d.get("line"),
            suggestion=str(d.get("suggestion") or d.get("fix") or ""),
            confidence=str(d.get("confidence") or "medium"),
        ).normalized()


@dataclass
class ReviewResult:
    findings: List[Finding] = field(default_factory=list)
    summary: str = ""
    files_reviewed: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    duration_s: float = 0.0
    from_cache: bool = False

    def blocking(self, threshold: str) -> List[Finding]:
        t = severity_rank(threshold)
        return [f for f in self.findings if f.rank >= t]

    def counts(self) -> Dict[str, int]:
        out = {s: 0 for s in SEVERITY_ORDER}
        for f in self.findings:
            out[f.severity] = out.get(f.severity, 0) + 1
        return out

    def sorted_findings(self) -> List[Finding]:
        return sorted(self.findings, key=lambda f: (-f.rank, f.file, f.line or 0))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary,
            "provider": self.provider,
            "model": self.model,
            "duration_s": round(self.duration_s, 2),
            "files_reviewed": self.files_reviewed,
            "counts": self.counts(),
            "errors": self.errors,
            "findings": [f.to_dict() for f in self.sorted_findings()],
        }
