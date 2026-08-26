#!/usr/bin/env python3
"""Build the one-page monochrome AI code reviewer comparison PDF.

    python3 docs/build_onepager.py [output.pdf]

Layout rule: every block measures its own text before drawing, so nothing
overflows its box. Do not hard-code box heights.
"""

import sys
from pathlib import Path

from reportlab.lib.colors import Color
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

# ---------------------------------------------------------------- palette
BLACK = Color(0, 0, 0)
INK = Color(0.13, 0.13, 0.13)
MID = Color(0.40, 0.40, 0.40)
LIGHT = Color(0.68, 0.68, 0.68)
HAIR = Color(0.86, 0.86, 0.86)
WASH = Color(0.945, 0.945, 0.945)
WHITE = Color(1, 1, 1)

REG, BOLD, OBL = "Helvetica", "Helvetica-Bold", "Helvetica-Oblique"

PAGE_W, PAGE_H = A4
M = 14 * mm
CW = PAGE_W - 2 * M
PAD = 7

# ---------------------------------------------------------------- data
# name, $/dev/mo, $/yr @ 12 devs, usage visibility, self-host, category, note
TOOLS = [
    ("SonarQube for IDE", "$0", "$0", "Yes — admin panel", "Yes (default)",
     "Static analysis",
     "Free plugin, runs in Cursor. Self-hosted Community Build server; per-user usage under "
     "Admin > Security > Users. Will not reason about logic."),
    ("aicr (in-house)", "~$0", "~$200", "Would need building", "Yes",
     "LLM (your choice)",
     "Already built: Cursor agent gate, /aicr-review, /aicr-fix, pre-push hook. "
     "Reporting layer not written yet."),
    ("Bito", "$12", "$1,728+", "Yes", "Enterprise", "LLM",
     "Cheapest with a dashboard. Watch the cap: 5K reviewed lines per seat per month, "
     "then $5 per 1K — can triple the bill."),
    ("Codacy", "$15", "$2,160", "Yes", "Enterprise", "Analysis + guardrails",
     "Quality, SAST, SCA and secrets in one platform. Real-time scanning in Cursor. "
     "Breadth over depth."),
    ("Qodo Merge Pro", "$19", "$2,736", "Enterprise only", "Yes (on-prem)", "LLM, strong",
     "Best governance if you reach Enterprise: audit logs, BYOK, air-gapped deploy. "
     "The dashboard you need is Enterprise-only."),
    ("CodeRabbit Pro", "$24", "$3,456", "Yes — best available", "Enterprise",
     "LLM, low noise",
     "Cursor plugin + VS Code extension + CLI, reviews on local commit. The only per-user "
     "IDE adoption dashboard on the market."),
    ("Snyk Team", "$25", "$3,600+", "Yes", "No", "Security only",
     "Best-in-class security depth, but will not catch broken logic — which is most of "
     "what the manager currently catches by hand."),
    ("Semgrep Team", "$35", "$5,040", "Yes", "Yes (OSS core)", "Rules engine",
     "Excellent custom-rule engine, strong free OSS tier if self-hosted. "
     "Priciest per seat here."),
]

COLS = [0.265, 0.070, 0.090, 0.180, 0.145, 0.250]
HEADS = ["TOOL", "$/DEV", "$/YEAR", "USAGE VISIBILITY", "SELF-HOST", "CATEGORY"]


def wrap(text, font, size, max_w):
    lines, cur = [], ""
    for w in text.split():
        trial = f"{cur} {w}".strip()
        if stringWidth(trial, font, size) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def build(out_path):
    c = canvas.Canvas(str(out_path), pagesize=A4)
    c.setTitle("AI Code Reviewer Options — 12 Developers")
    c.setAuthor("Praeclarum Engineering")
    c.setSubject("IDE-based AI code review tooling, costed for a 12-developer team")

    y = PAGE_H - M

    # ---------------------------------------------------- title
    c.setFillColor(BLACK)
    c.setFont(BOLD, 17)
    c.drawString(M, y - 13, "AI Code Reviewer Options")
    c.setFont(REG, 9.5)
    c.setFillColor(MID)
    c.drawRightString(M + CW, y - 13, "Costed for 12 developers   ·   August 2026")
    y -= 19
    c.setStrokeColor(BLACK)
    c.setLineWidth(1.4)
    c.line(M, y, M + CW, y)
    y -= 6
    c.setFont(REG, 8.6)
    c.setFillColor(MID)
    c.drawString(M, y - 8, "IDE-first tools that run in Cursor and VS Code. Prices are per "
                           "developer per month, annual billing where available.")
    y -= 22

    # ---------------------------------------------------- constraint box
    head = "THE CONSTRAINT"
    lead = "“IDE-only” and “manager can see usage” pull against each other."
    body = ("A purely local tool cannot report to anyone. Every option below has a cloud or "
            "self-hosted backend — that backend is what makes the manager’s view "
            "possible. What you are ruling out is a bot commenting on pull requests, not a server.")
    body_lines = wrap(body, REG, 8.4, CW - 2 * PAD)
    bh = 14 + 11 + 9.8 * len(body_lines) + 4

    c.setFillColor(WASH)
    c.rect(M, y - bh, CW, bh, stroke=0, fill=1)
    c.setStrokeColor(BLACK)
    c.setLineWidth(1.0)
    c.rect(M, y - bh, CW, bh, stroke=1, fill=0)

    c.setFillColor(BLACK)
    c.setFont(BOLD, 9)
    c.drawString(M + PAD, y - 13, head)
    c.setFont(REG, 8.7)
    c.setFillColor(INK)
    c.drawString(M + PAD + stringWidth(head, BOLD, 9) + 8, y - 13, lead)
    c.setFont(REG, 8.4)
    c.setFillColor(MID)
    ly = y - 25
    for ln in body_lines:
        c.drawString(M + PAD, ly, ln)
        ly -= 9.8
    y -= bh + 15

    # ---------------------------------------------------- table
    xs, acc = [], M
    for f in COLS:
        xs.append(acc)
        acc += f * CW
    widths = [f * CW for f in COLS]

    hh = 15
    c.setFillColor(BLACK)
    c.rect(M, y - hh, CW, hh, stroke=0, fill=1)
    c.setFillColor(WHITE)
    c.setFont(BOLD, 8.0)
    for i, h in enumerate(HEADS):
        c.drawString(xs[i] + 5, y - 10.3, h)
    y -= hh
    table_top = y

    note_w = widths[0] + widths[1] + widths[2] + widths[3] - 10
    for idx, (name, mo, yr, vis, host, cat, note) in enumerate(TOOLS):
        note_lines = wrap(note, OBL, 7.5, note_w)
        rh = 13 + 9.2 * len(note_lines) + 5

        if idx % 2 == 0:
            c.setFillColor(WASH)
            c.rect(M, y - rh, CW, rh, stroke=0, fill=1)
        c.setStrokeColor(HAIR)
        c.setLineWidth(0.5)
        c.line(M, y - rh, M + CW, y - rh)

        ty = y - 11
        c.setFillColor(BLACK)
        c.setFont(BOLD, 8.5)
        c.drawString(xs[0] + 5, ty, name)
        c.setFont(REG, 8.5)
        c.setFillColor(INK)
        c.drawString(xs[1] + 5, ty, mo)
        c.setFont(BOLD, 8.5)
        c.drawString(xs[2] + 5, ty, yr)
        c.setFont(REG, 8.2)
        c.setFillColor(INK)
        c.drawString(xs[3] + 5, ty, vis)
        c.drawString(xs[4] + 5, ty, host)
        c.setFillColor(MID)
        c.drawString(xs[5] + 5, ty, cat)

        c.setFont(OBL, 7.5)
        c.setFillColor(MID)
        ny = ty - 9.6
        for ln in note_lines:
            c.drawString(xs[0] + 5, ny, ln)
            ny -= 9.2
        y -= rh

    c.setStrokeColor(BLACK)
    c.setLineWidth(0.9)
    c.rect(M, y, CW, table_top - y, stroke=1, fill=0)
    y -= 14

    # ---------------------------------------------------- set aside
    rows = [
        ("Cursor Bugbot", "~$4,700–7,000/yr, usage-billed — rejected on cost."),
        ("Greptile", "$4,320/yr. Best bug detection, but PR-centric with no analytics "
                     "dashboard at all, so the manager cannot see adoption."),
    ]
    lab_w = max(stringWidth(r[0], BOLD, 8.2) for r in rows) + 10
    wrapped = [(lab, wrap(txt, REG, 8.2, CW - 2 * PAD - lab_w)) for lab, txt in rows]
    bh = 14 + sum(9.6 * len(w) for _, w in wrapped) + 4

    c.setStrokeColor(LIGHT)
    c.setLineWidth(0.7)
    c.rect(M, y - bh, CW, bh, stroke=1, fill=0)
    c.setFillColor(MID)
    c.setFont(BOLD, 8.2)
    c.drawString(M + PAD, y - 12, "CONSIDERED AND SET ASIDE")
    ly = y - 24
    for lab, lines in wrapped:
        c.setFont(BOLD, 8.2)
        c.setFillColor(INK)
        c.drawString(M + PAD, ly, lab)
        c.setFont(REG, 8.2)
        c.setFillColor(MID)
        for i, ln in enumerate(lines):
            c.drawString(M + PAD + lab_w, ly, ln)
            ly -= 9.6
    y -= bh + 14

    # ---------------------------------------------------- recommendation
    recs = [
        ("Start free, this week.",
         "SonarQube for IDE in Connected Mode against a self-hosted Community Build server. "
         "Costs nothing, runs in Cursor, gives per-user visibility, and pushes team rules into "
         "every editor. Pair it with aicr — static analysis and LLM review catch different "
         "bug classes, and together they run about $200 a year."),
        ("If a dashboard is the priority:",
         "CodeRabbit Pro at $3,456/yr. The only tool where “who is actually using this” "
         "is a supported view rather than something you assemble, and roughly half the cost of "
         "Bugbot."),
        ("Before paying anyone:",
         "every option here has a free tier or trial. Run two of them on the same week of real "
         "work. Vendor benchmarks disagree because each vendor’s test favours that vendor "
         "— your codebase is the only benchmark that counts."),
    ]
    wrapped = []
    for lab, txt in recs:
        first_w = CW - 2 * PAD - stringWidth(lab, BOLD, 8.3) - 4
        words, first, rest = txt.split(), "", ""
        for i, w in enumerate(words):
            trial = f"{first} {w}".strip()
            if stringWidth(trial, REG, 8.3) <= first_w:
                first = trial
            else:
                rest = " ".join(words[i:])
                break
        wrapped.append((lab, first, wrap(rest, REG, 8.3, CW - 2 * PAD) if rest else []))
    bh = 16 + 8 + sum(9.8 * (1 + len(r)) for _, _, r in wrapped) + 5

    c.setStrokeColor(BLACK)
    c.setLineWidth(1.2)
    c.rect(M, y - bh, CW, bh, stroke=1, fill=0)
    c.setFillColor(BLACK)
    c.rect(M, y - 16, CW, 16, stroke=0, fill=1)
    c.setFillColor(WHITE)
    c.setFont(BOLD, 9)
    c.drawString(M + PAD, y - 11.5, "RECOMMENDATION")

    ly = y - 29
    for lab, first, rest in wrapped:
        c.setFont(BOLD, 8.3)
        c.setFillColor(BLACK)
        c.drawString(M + PAD, ly, lab)
        c.setFont(REG, 8.3)
        c.setFillColor(INK)
        c.drawString(M + PAD + stringWidth(lab, BOLD, 8.3) + 4, ly, first)
        ly -= 9.8
        for ln in rest:
            c.drawString(M + PAD, ly, ln)
            ly -= 9.8
    y -= bh + 16

    # ---------------------------------------------------- footer
    c.setStrokeColor(LIGHT)
    c.setLineWidth(0.6)
    c.line(M, y + 6, M + CW, y + 6)
    c.setFont(REG, 6.9)
    c.setFillColor(MID)
    c.drawString(M, y - 3,
                 "Official pricing and docs: CodeRabbit, Qodo, SonarQube, Bito, Greptile.")
    c.drawString(M, y - 12,
                 "Third-party comparisons: Codacy, Snyk, Semgrep, SonarQube paid editions "
                 "— confirm with the vendor before budgeting.")
    c.drawRightString(M + CW, y - 12, "Praeclarum Engineering")

    c.showPage()
    c.save()
    return out_path


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        Path(__file__).resolve().parent / "ai-code-reviewer-options.pdf"
    build(out)
    print(f"wrote {out}")
