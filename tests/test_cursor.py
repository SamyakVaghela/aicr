"""Cursor IDE integration: project hooks, slash commands, agent push gate."""

import json

import pytest

from aicr import cursorinit
from aicr.cli import main

BAD_PY = 'API_KEY = "sk-live-supersecretvalue123"\n'
GOOD_PY = "def add(a, b):\n    return a + b\n"


@pytest.fixture(autouse=True)
def mock_provider(monkeypatch):
    monkeypatch.setenv("AICR_PROVIDER", "mock")
    monkeypatch.setenv("AICR_CACHE", "0")


def _hook_stdin(monkeypatch, payload):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))


def _run_hook(capsys):
    code = main(["cursor-hook"])
    out = json.loads(capsys.readouterr().out)
    return code, out


# --------------------------------------------------------------- installation

def test_cursor_init_writes_hooks_and_commands(repo, capsys):
    assert main(["cursor-init", "--repo", str(repo)]) == 0
    hooks = json.loads((repo / ".cursor" / "hooks.json").read_text())
    entries = hooks["hooks"]["beforeShellExecution"]
    assert any(e["command"] == "aicr cursor-hook" for e in entries)
    assert (repo / ".cursor" / "commands" / "aicr-review.md").exists()
    assert (repo / ".cursor" / "commands" / "aicr-fix.md").exists()
    assert "installed" in cursorinit.status(repo)


def test_cursor_init_merges_with_existing_hooks(repo):
    cdir = repo / ".cursor"
    cdir.mkdir()
    (cdir / "hooks.json").write_text(json.dumps({
        "version": 1,
        "hooks": {
            "afterFileEdit": [{"command": "./format.sh"}],
            "beforeShellExecution": [{"command": "./audit.sh"}],
        },
    }))
    main(["cursor-init", "--repo", str(repo)])
    hooks = json.loads((cdir / "hooks.json").read_text())
    cmds = [e["command"] for e in hooks["hooks"]["beforeShellExecution"]]
    assert "./audit.sh" in cmds          # existing hook preserved
    assert "aicr cursor-hook" in cmds    # ours added
    assert hooks["hooks"]["afterFileEdit"] == [{"command": "./format.sh"}]


def test_cursor_init_is_idempotent(repo):
    main(["cursor-init", "--repo", str(repo)])
    main(["cursor-init", "--repo", str(repo)])
    hooks = json.loads((repo / ".cursor" / "hooks.json").read_text())
    entries = [e for e in hooks["hooks"]["beforeShellExecution"]
               if e["command"] == "aicr cursor-hook"]
    assert len(entries) == 1


def test_cursor_init_rejects_broken_json(repo):
    cdir = repo / ".cursor"
    cdir.mkdir()
    (cdir / "hooks.json").write_text("{not json")
    assert main(["cursor-init", "--repo", str(repo)]) == 2


def test_cursor_uninstall(repo):
    main(["cursor-init", "--repo", str(repo)])
    main(["cursor-init", "--repo", str(repo), "--uninstall"])
    assert cursorinit.status(repo) in ("not installed",
                                       "hooks.json exists but has no aicr hook")
    assert not (repo / ".cursor" / "commands" / "aicr-review.md").exists()


# ----------------------------------------------------------------- the gate

def test_hook_allows_non_push_commands(repo, commit, monkeypatch, capsys):
    commit("app.py", BAD_PY)
    _hook_stdin(monkeypatch, {"command": "npm test", "cwd": str(repo)})
    code, out = _run_hook(capsys)
    assert code == 0 and out["permission"] == "allow"


def test_hook_denies_push_with_blocking_findings(repo, commit, monkeypatch, capsys):
    commit("app.py", BAD_PY)
    _hook_stdin(monkeypatch, {"command": "git push origin main", "cwd": str(repo)})
    code, out = _run_hook(capsys)
    assert code == 0                      # the hook itself always succeeds
    assert out["permission"] == "deny"
    assert "Hardcoded credential" in out["agent_message"]
    assert "no-verify" in out["agent_message"]   # tells the agent not to bypass
    assert "blocked" in out["user_message"].lower()


def test_hook_allows_clean_push(repo, commit, monkeypatch, capsys):
    commit("app.py", GOOD_PY)
    _hook_stdin(monkeypatch, {"command": "git push", "cwd": str(repo)})
    code, out = _run_hook(capsys)
    assert out["permission"] == "allow"


def test_hook_gates_no_verify_push_too(repo, commit, monkeypatch, capsys):
    """--no-verify skips the git hook, so the Cursor hook must still catch it."""
    commit("app.py", BAD_PY)
    _hook_stdin(monkeypatch, {"command": "git push --no-verify", "cwd": str(repo)})
    _, out = _run_hook(capsys)
    assert out["permission"] == "deny"


def test_hook_allows_when_nothing_to_push(repo, monkeypatch, capsys):
    _hook_stdin(monkeypatch, {"command": "git push", "cwd": str(repo)})
    _, out = _run_hook(capsys)
    assert out["permission"] == "allow"


def test_hook_allows_on_provider_misconfiguration(repo, commit, monkeypatch, capsys):
    """A broken reviewer must not wedge the agent — but must say so."""
    commit("app.py", BAD_PY)
    monkeypatch.setenv("AICR_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _hook_stdin(monkeypatch, {"command": "git push", "cwd": str(repo)})
    code, out = _run_hook(capsys)
    assert code == 0
    assert out["permission"] == "allow"
    assert "aicr" in out["user_message"]


def test_hook_survives_garbage_stdin(monkeypatch, capsys):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("not json at all"))
    code, out = _run_hook(capsys)
    assert code == 0 and out["permission"] == "allow"


def test_hook_survives_empty_stdin(monkeypatch, capsys):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    code, out = _run_hook(capsys)
    assert code == 0 and out["permission"] == "allow"


def test_decide_matches_push_variants():
    for cmd in ("git push", "git push origin main", "git push --no-verify",
                "git -C /repo push", "cd x && git push"):
        assert cursorinit.decide({"command": cmd})[0], cmd
    for cmd in ("git status", "npm run push-docs", "echo git", "git pull"):
        assert not cursorinit.decide({"command": cmd})[0], cmd


# ------------------------------------------------------- GUI report fallback

def test_blocked_push_writes_report_file(repo, commit, monkeypatch):
    """Cursor's Source Control panel hides hook output — leave a file behind."""
    commit("app.py", BAD_PY)
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert main(["pre-push", "--repo", str(repo)]) == 1
    report = repo / ".aicr-review.md"
    assert report.exists()
    assert "Hardcoded credential" in report.read_text()


def test_clean_push_leaves_no_report(repo, commit, monkeypatch):
    commit("app.py", GOOD_PY)
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert main(["pre-push", "--repo", str(repo)]) == 0
    assert not (repo / ".aicr-review.md").exists()


def test_init_gitignores_the_report(repo):
    main(["init", "--repo", str(repo)])
    assert ".aicr-review.md" in (repo / ".gitignore").read_text()
