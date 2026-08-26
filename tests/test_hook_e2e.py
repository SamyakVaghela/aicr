"""End-to-end: install the hook, then actually run `git push` and check it blocks."""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

BAD_PY = 'API_KEY = "sk-live-supersecretvalue123"\n'
GOOD_PY = "def add(a, b):\n    return a + b\n"

SRC = Path(__file__).resolve().parents[1] / "src"


def _install_shim_hook(repo: Path) -> None:
    """Install a hook that calls this interpreter directly, so the test does not
    depend on `aicr` being pip-installed on PATH."""
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    hook = hooks / "pre-push"
    hook.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env bash
        set -uo pipefail
        if [ "${{AICR_DISABLE:-0}}" = "1" ]; then exit 0; fi
        PYTHONPATH="{SRC}" "{sys.executable}" -m aicr pre-push "$@" < /dev/stdin
        exit $?
    """))
    hook.chmod(0o755)


def _commit(repo: Path, rel: str, body: str) -> None:
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text(body)
    subprocess.run(["git", "add", rel], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", f"add {rel}"], cwd=repo, check=True)


def _push(repo: Path, *extra: str):
    env = {**os.environ, "AICR_PROVIDER": "mock", "AICR_CACHE": "0", "NO_COLOR": "1"}
    return subprocess.run(["git", "push", *extra, "origin", "main"],
                          cwd=repo, capture_output=True, text=True, env=env)


def test_push_is_blocked_then_allowed_after_fix(repo):
    _install_shim_hook(repo)

    _commit(repo, "secrets.py", BAD_PY)
    blocked = _push(repo)
    assert blocked.returncode != 0, blocked.stdout + blocked.stderr
    assert "PUSH BLOCKED" in blocked.stderr
    assert "Hardcoded credential" in blocked.stderr

    _commit(repo, "secrets.py", "API_KEY = os.environ['API_KEY']\n")
    fixed = _push(repo)
    assert fixed.returncode == 0, fixed.stdout + fixed.stderr


def test_clean_change_pushes_without_blocking(repo):
    _install_shim_hook(repo)
    _commit(repo, "math_utils.py", GOOD_PY)
    res = _push(repo)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "No issues found" in res.stderr or "Push allowed" in res.stderr


def test_no_verify_bypasses_the_hook(repo):
    _install_shim_hook(repo)
    _commit(repo, "secrets.py", BAD_PY)
    res = _push(repo, "--no-verify")
    assert res.returncode == 0, res.stdout + res.stderr


def test_aicr_disable_env_bypasses(repo):
    _install_shim_hook(repo)
    _commit(repo, "secrets.py", BAD_PY)
    env = {**os.environ, "AICR_DISABLE": "1"}
    res = subprocess.run(["git", "push", "origin", "main"], cwd=repo,
                         capture_output=True, text=True, env=env)
    assert res.returncode == 0, res.stdout + res.stderr


def test_docs_only_push_is_not_blocked(repo):
    _install_shim_hook(repo)
    _commit(repo, "docs/guide.md", "# Guide\n\nSome text.\n")
    res = _push(repo)
    assert res.returncode == 0, res.stdout + res.stderr


def _commit_shared_shim_hook(repo: Path) -> None:
    """What the FIRST developer does: write the committable hook and commit it
    — same shim pattern as _install_shim_hook (PYTHONPATH-aware, no real pip
    install needed), just living in .githooks/ instead of .git/hooks/."""
    hooks = repo / ".githooks"
    hooks.mkdir(parents=True, exist_ok=True)
    hook = hooks / "pre-push"
    hook.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env bash
        set -uo pipefail
        if [ "${{AICR_DISABLE:-0}}" = "1" ]; then exit 0; fi
        PYTHONPATH="{SRC}" "{sys.executable}" -m aicr pre-push "$@" < /dev/stdin
        exit $?
    """))
    hook.chmod(0o755)
    subprocess.run(["git", "add", ".githooks"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "add shared pre-push hook"], cwd=repo, check=True)


def test_shared_hook_gates_a_fresh_clone_with_one_git_config_command(repo, tmp_path):
    """The actual claim: a second developer who does nothing but clone and run
    `git config core.hooksPath .githooks` — never `aicr install-hook` — still
    gets gated. That one command is the floor git allows (see hookinstall.py:
    install_shared and CLAUDE.md on why zero commands isn't possible)."""
    _commit_shared_shim_hook(repo)
    subprocess.run(["git", "push", "origin", "main"], cwd=repo, check=True,
                   capture_output=True)

    # conftest's `repo` fixture points origin at a bare repo — clone from that
    # same bare origin, matching what a real teammate would do.
    origin = subprocess.run(["git", "-C", str(repo), "remote", "get-url", "origin"],
                            check=True, capture_output=True, text=True).stdout.strip()
    clone = tmp_path / "teammate-clone"
    subprocess.run(["git", "clone", origin, str(clone)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(clone), "config", "user.email", "teammate@example.com"],
                   check=True)
    subprocess.run(["git", "-C", str(clone), "config", "user.name", "Teammate"], check=True)
    subprocess.run(["git", "-C", str(clone), "config", "commit.gpgsign", "false"], check=True)

    # The one and only setup command a teammate runs — no aicr install-hook.
    subprocess.run(["git", "-C", str(clone), "config", "core.hooksPath", ".githooks"], check=True)

    _commit(clone, "secrets.py", BAD_PY)
    res = _push(clone)
    assert res.returncode != 0, res.stdout + res.stderr
    assert "PUSH BLOCKED" in res.stderr
