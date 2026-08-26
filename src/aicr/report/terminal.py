"""Human-readable terminal output."""

from __future__ import annotations

import os
import shutil
import sys
from typing import List

from ..models import ReviewResult, severity_rank

_COLORS = {
    "critical": "\033[1;97;41m",
    "high": "\033[1;31m",
    "medium": "\033[1;33m",
    "low": "\033[0;36m",
    "info": "\033[0;90m",
    "ok": "\033[1;32m",
    "dim": "\033[0;90m",
    "bold": "\033[1m",
    "reset": "\033[0m",
}

_LABEL = {
    "critical": "CRITICAL",
    "high": "HIGH    ",
    "medium": "MEDIUM  ",
    "low": "LOW     ",
    "info": "INFO    ",
}


def _use_color(stream) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("AICR_FORCE_COLOR"):
        return True
    return hasattr(stream, "isatty") and stream.isatty()


def _wrap(text: str, width: int, indent: str) -> str:
    import textwrap
    if not text:
        return ""
    lines: List[str] = []
    for para in text.splitlines():
        lines.extend(textwrap.wrap(para, width=width, initial_indent=indent,
                                   subsequent_indent=indent) or [indent.rstrip()])
    return "\n".join(lines)


def render_terminal(result: ReviewResult, fail_on: str, stream=None, quiet_passes: bool = False) -> str:
    stream = stream or sys.stdout
    color = _use_color(stream)
    width = min(shutil.get_terminal_size((100, 24)).columns, 100)

    def c(key: str, text: str) -> str:
        return f"{_COLORS[key]}{text}{_COLORS['reset']}" if color else text

    out: List[str] = []
    rule = "─" * width
    out.append(c("dim", rule))
    header = f" AI CODE REVIEW  ·  {result.provider}/{result.model}"
    if result.from_cache:
        header += "  (cached)"
    out.append(c("bold", header))
    out.append(c("dim", f" {len(result.files_reviewed)} file(s) · {result.duration_s:.1f}s"))
    out.append(c("dim", rule))

    blocking = result.blocking(fail_on)
    threshold = severity_rank(fail_on)

    if result.summary and not quiet_passes:
        out.append("")
        out.append(_wrap(result.summary, width - 2, " "))

    if result.findings:
        out.append("")
        for f in result.sorted_findings():
            gate = "BLOCKS PUSH" if f.rank >= threshold else "advisory"
            loc = f"{f.file}:{f.line}" if f.line else f.file
            out.append(
                f"{c(f.severity, ' ' + _LABEL.get(f.severity, f.severity.upper()) + ' ')}  "
                f"{c('bold', f.title)}"
            )
            out.append(c("dim", f"           {loc}  ·  {f.category}  ·  {gate}"
                                f"  ·  confidence: {f.confidence}"))
            if f.detail:
                out.append(_wrap(f.detail, width - 12, " " * 11))
            if f.suggestion:
                out.append(c("dim", " " * 11 + "Fix:"))
                out.append(_wrap(f.suggestion, width - 12, " " * 11))
            out.append("")

    counts = result.counts()
    parts = [f"{counts[s]} {s}" for s in ("critical", "high", "medium", "low", "info") if counts[s]]
    out.append(c("dim", rule))
    if not result.findings:
        out.append(c("ok", " ✓  No issues found."))
    else:
        out.append(" " + ", ".join(parts))

    if result.errors:
        out.append("")
        for e in result.errors:
            out.append(c("medium", f" ! {e}"))

    if blocking:
        out.append("")
        out.append(c("high", f" ✗  PUSH BLOCKED — {len(blocking)} issue(s) at "
                             f"'{fail_on}' or above must be fixed."))
        out.append(c("dim", "    Fix them, commit, and push again."))
        out.append(c("dim", "    Emergency override: git push --no-verify"))
    elif result.findings:
        out.append("")
        out.append(c("ok", " ✓  Push allowed — no blocking issues."))
    out.append(c("dim", rule))
    return "\n".join(out)
