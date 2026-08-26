"""Install aicr's GitHub Actions integration: a PR comment with the review.

Writes one committed file, so the whole team gets it on `git pull`:

  .github/workflows/aicr-review.yml

This is the CI companion to the local pre-push hook, not a replacement for
it — see docs/ROLLOUT.md "Seeing who's actually running it". It runs on every
push to a pull request, reviews the PR's diff, and posts (or updates) a single
comment on the PR with the findings, so a reviewer or manager reads them right
next to the code. By default it never fails the check and never blocks
merging — it is visibility, not a gate. Turning it into a required status
check is a one-line change to the workflow, called out in the file itself.

Unlike the pre-push hook, this runs on GitHub's infrastructure with a token
GitHub issues automatically, so it also comments on a PR whose author pushed
with `--no-verify` — the one blind spot the local-only tool has.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

WORKFLOW_PATH = ".github/workflows/aicr-review.yml"

WORKFLOW_YAML = """\
# aicr — post the AI code review as a PR comment.
#
# EDIT ME: point this at wherever your org hosts aicr (PyPI, an internal
# index, or a git URL). It is not on the public PyPI.
#
# This job only comments — it never fails the check or blocks merging. To
# make it a required, unavoidable gate instead (the local pre-push hook can
# always be skipped with --no-verify, this cannot), remove the
# `continue-on-error: true` below and mark this workflow as a required
# status check in the repo's branch protection settings.

name: aicr review

on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write

concurrency:
  group: aicr-review-${{ github.event.pull_request.number }}
  cancel-in-progress: true

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
          ref: ${{ github.event.pull_request.head.sha }}

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - name: Install aicr
        run: pip install "aicr @ git+https://github.com/YOUR-ORG/aicr.git@main"

      - name: Run the review
        id: review
        continue-on-error: true
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
        run: |
          aicr review \\
            --range "${{ github.event.pull_request.base.sha }}..${{ github.event.pull_request.head.sha }}" \\
            --format markdown --out review.md
          echo "exit_code=$?" >> "$GITHUB_OUTPUT"

      - name: Post or update the PR comment
        if: always() && hashFiles('review.md') != ''
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          set -euo pipefail
          MARKER="<!-- aicr-review -->"
          BODY_FILE="$(mktemp)"
          { echo "$MARKER"; echo; cat review.md; } > "$BODY_FILE"

          EXISTING_ID=$(gh api "repos/${{ github.repository }}/issues/${{ github.event.pull_request.number }}/comments" \\
            --paginate --jq ".[] | select(.body | startswith(\\"$MARKER\\")) | .id" | head -n1)

          if [ -n "$EXISTING_ID" ]; then
            gh api "repos/${{ github.repository }}/issues/comments/$EXISTING_ID" \\
              -X PATCH -f body=@"$BODY_FILE" > /dev/null
          else
            gh pr comment "${{ github.event.pull_request.number }}" --body-file "$BODY_FILE"
          fi
"""


def install(root: Path, force: bool = False) -> List[str]:
    """Write the GitHub Actions workflow. Returns human-readable actions."""
    target = root / WORKFLOW_PATH
    if target.exists() and not force:
        return [f"{target} already exists (unchanged) — rerun with --force to overwrite"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(WORKFLOW_YAML, encoding="utf-8")
    return [f"wrote {target}"]


def uninstall(root: Path) -> List[str]:
    target = root / WORKFLOW_PATH
    if not target.exists():
        return ["nothing to remove"]
    target.unlink()
    return [f"removed {target}"]


def status(root: Path) -> str:
    target = root / WORKFLOW_PATH
    return "installed" if target.exists() else "not installed"
