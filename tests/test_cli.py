import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from aicr import hookinstall
from aicr.cli import main

BAD_PY = '''\
import sqlite3

API_KEY = "sk-live-supersecretvalue123"

def lookup(conn, name):
    return conn.execute("SELECT * FROM users WHERE name = '" + name + "'")
'''

GOOD_PY = '''\
def add(a, b):
    """Return the sum of two numbers."""
    return a + b
'''


@pytest.fixture(autouse=True)
def mock_provider(monkeypatch):
    monkeypatch.setenv("AICR_PROVIDER", "mock")
    monkeypatch.setenv("AICR_CACHE", "0")
    monkeypatch.delenv("AICR_FAIL_ON", raising=False)


def test_init_writes_config_and_gitignore(repo, capsys):
    assert main(["init", "--repo", str(repo)]) == 0
    cfg = repo / ".aicr.toml"
    assert cfg.exists() and "custom_rules" in cfg.read_text()
    assert ".aicr.local.toml" in (repo / ".gitignore").read_text()


def test_init_refuses_overwrite(repo):
    main(["init", "--repo", str(repo)])
    assert main(["init", "--repo", str(repo)]) == 2
    assert main(["init", "--repo", str(repo), "--force"]) == 0


def test_install_hook(repo):
    assert main(["install-hook", "--repo", str(repo)]) == 0
    hook = hookinstall.hooks_dir(repo) / "pre-push"
    assert hook.exists() and os.access(hook, os.X_OK)
    assert "aicr pre-push" in hook.read_text() or "pre-push" in hook.read_text()
    assert "installed at" in hookinstall.status(repo)


def test_install_hook_respects_foreign_hook(repo):
    hdir = hookinstall.hooks_dir(repo)
    hdir.mkdir(parents=True, exist_ok=True)
    (hdir / "pre-push").write_text("#!/bin/sh\necho mine\n")
    assert main(["install-hook", "--repo", str(repo)]) == 2
    assert main(["install-hook", "--repo", str(repo), "--force"]) == 0
    assert any(p.name.startswith("pre-push.pre-aicr") for p in hdir.iterdir())


def test_uninstall_hook(repo):
    main(["install-hook", "--repo", str(repo)])
    assert main(["uninstall-hook", "--repo", str(repo)]) == 0
    assert hookinstall.status(repo) == "not installed"


def test_review_blocks_on_critical(repo, commit, capsys):
    commit("app.py", BAD_PY)
    code = main(["review", "--repo", str(repo), "--format", "json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 1
    assert out["blocked"] is True
    sevs = {f["severity"] for f in out["findings"]}
    assert "critical" in sevs
    assert out["findings"][0]["file"] == "app.py"


def test_review_passes_clean_code(repo, commit, capsys):
    commit("app.py", GOOD_PY)
    assert main(["review", "--repo", str(repo), "--format", "json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["blocked"] is False


def test_fail_on_override_changes_verdict(repo, commit):
    commit("app.py", "def f():\n    print('debug')\n")   # only a 'low' finding
    assert main(["review", "--repo", str(repo), "--format", "json"]) == 0
    assert main(["review", "--repo", str(repo), "--format", "json", "--fail-on", "low"]) == 1


def test_review_nothing_to_push(repo):
    assert main(["review", "--repo", str(repo)]) == 0


def test_review_staged(repo, capsys):
    (repo / "s.py").write_text(BAD_PY)
    subprocess.run(["git", "add", "s.py"], cwd=repo, check=True)
    assert main(["review", "--repo", str(repo), "--staged", "--format", "json"]) == 1


def test_markdown_report_and_out_file(repo, commit, tmp_path, capsys):
    commit("app.py", BAD_PY)
    out = tmp_path / "report.md"
    main(["review", "--repo", str(repo), "--format", "markdown", "--out", str(out)])
    md = capsys.readouterr().out
    assert "# AI Code Review" in md and "Blocked" in md
    assert out.exists() and "app.py" in out.read_text()


def test_repo_command_reviews_tracked_files(repo, commit, capsys):
    commit("app.py", BAD_PY)
    code = main(["repo", "--repo", str(repo), "--format", "json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 1
    assert "app.py" in out["files_reviewed"]


def test_review_specific_files(repo, commit, capsys):
    commit("app.py", BAD_PY)
    commit("clean.py", GOOD_PY)
    main(["review", "--repo", str(repo), "--files", "clean.py", "--format", "json"])
    out = json.loads(capsys.readouterr().out)
    assert out["files_reviewed"] == ["clean.py"]
    assert out["blocked"] is False


def test_doctor(repo, capsys):
    assert main(["doctor", "--repo", str(repo)]) == 0
    assert "OK (mock)" in capsys.readouterr().out


def test_unknown_provider_is_an_error(repo, commit, monkeypatch):
    commit("app.py", GOOD_PY)
    monkeypatch.setenv("AICR_PROVIDER", "nope")
    assert main(["review", "--repo", str(repo)]) == 2


def test_missing_api_key_does_not_silently_pass(repo, commit, monkeypatch):
    """A misconfigured provider must not be treated as 'review passed'."""
    commit("app.py", BAD_PY)
    monkeypatch.setenv("AICR_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert main(["review", "--repo", str(repo)]) == 2
