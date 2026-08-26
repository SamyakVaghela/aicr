"""Markdown report — paste into a PR description or share with the manager."""

from __future__ import annotations

from ..models import ReviewResult, severity_rank

_EMOJI = {"critical": "🛑", "high": "🔴", "medium": "🟠", "low": "🔵", "info": "⚪"}


def render_markdown(result: ReviewResult, fail_on: str, title: str = "AI Code Review") -> str:
    threshold = severity_rank(fail_on)
    counts = result.counts()
    blocking = result.blocking(fail_on)

    lines = [f"# {title}", ""]
    lines.append(f"**Model:** `{result.provider}/{result.model}` · "
                 f"**Files:** {len(result.files_reviewed)} · "
                 f"**Duration:** {result.duration_s:.1f}s")
    lines.append("")
    verdict = ("❌ **Blocked** — "
               f"{len(blocking)} issue(s) at `{fail_on}` or above"
               ) if blocking else "✅ **Passed** — no blocking issues"
    lines.append(verdict)
    lines.append("")
    if result.summary:
        lines += ["> " + result.summary.replace("\n", " "), ""]

    if result.findings:
        lines.append("| Severity | File | Category | Issue |")
        lines.append("|---|---|---|---|")
        for f in result.sorted_findings():
            loc = f"`{f.file}:{f.line}`" if f.line else f"`{f.file}`"
            lines.append(f"| {_EMOJI.get(f.severity,'')} {f.severity} | {loc} | "
                         f"{f.category} | {f.title} |")
        lines.append("")
        lines.append("## Details")
        lines.append("")
        for f in result.sorted_findings():
            loc = f"{f.file}:{f.line}" if f.line else f.file
            gate = " — **blocks push**" if f.rank >= threshold else ""
            lines.append(f"### {_EMOJI.get(f.severity,'')} `{f.severity}` {f.title}{gate}")
            lines.append(f"`{loc}` · {f.category} · confidence: {f.confidence}")
            lines.append("")
            if f.detail:
                lines += [f.detail, ""]
            if f.suggestion:
                lines += ["**Suggested fix**", "", "```", f.suggestion, "```", ""]
    else:
        lines += ["No issues found.", ""]

    summary_bits = [f"{counts[s]} {s}" for s in
                    ("critical", "high", "medium", "low", "info") if counts[s]]
    if summary_bits:
        lines += ["---", "", "**Totals:** " + ", ".join(summary_bits), ""]

    if result.errors:
        lines += ["**Warnings during review**", ""]
        lines += [f"- {e}" for e in result.errors]
        lines.append("")

    if result.files_reviewed:
        lines.append("<details><summary>Files reviewed</summary>")
        lines.append("")
        lines += [f"- `{p}`" for p in result.files_reviewed]
        lines += ["", "</details>", ""]

    return "\n".join(lines)
