"""Local history + the opt-in admin webhook (see telemetry.py)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from aicr import telemetry
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

RECEIVED = {}


def _make_server(status=200):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", 0))
            RECEIVED["body"] = json.loads(self.rfile.read(length) or b"{}")
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):  # silence
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


@pytest.fixture(autouse=True)
def mock_provider(monkeypatch):
    monkeypatch.setenv("AICR_PROVIDER", "mock")
    monkeypatch.setenv("AICR_CACHE", "0")
    monkeypatch.delenv("AICR_TELEMETRY_WEBHOOK", raising=False)
    RECEIVED.clear()


def _history_lines():
    path = telemetry.history_path()
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def test_local_history_recorded_without_any_telemetry_config(repo, commit):
    commit("app.py", BAD_PY)
    assert main(["review", "--repo", str(repo), "--format", "json"]) == 1

    lines = _history_lines()
    assert len(lines) == 1
    event = lines[0]
    assert event["source"] == "review"
    assert event["blocked"] is True
    assert event["user"] == "dev@example.com"
    assert event["repo"] == repo.name
    assert event["counts"]["critical"] >= 1
    assert "findings" not in event  # include_findings defaults to False


def test_no_webhook_call_when_telemetry_disabled(repo, commit, monkeypatch):
    srv, url = _make_server()
    try:
        (repo / ".aicr.toml").write_text(
            f'[telemetry]\nenabled = false\nwebhook_url = "{url}"\n'
        )
        commit("app.py", GOOD_PY)
        assert main(["review", "--repo", str(repo), "--format", "json"]) == 0
        assert "body" not in RECEIVED
        assert _history_lines()  # still logged locally
    finally:
        srv.shutdown()


def test_webhook_posts_event_when_enabled(repo, commit):
    srv, url = _make_server()
    try:
        (repo / ".aicr.toml").write_text(
            f'[telemetry]\nenabled = true\nwebhook_url = "{url}"\n'
        )
        commit("app.py", BAD_PY)
        assert main(["review", "--repo", str(repo), "--format", "json"]) == 1

        assert RECEIVED["body"]["source"] == "review"
        assert RECEIVED["body"]["blocked"] is True
        assert RECEIVED["body"]["user"] == "dev@example.com"
        assert RECEIVED["body"]["counts"]["critical"] >= 1
        assert "findings" not in RECEIVED["body"]
    finally:
        srv.shutdown()


def test_include_findings_opt_in(repo, commit):
    srv, url = _make_server()
    try:
        (repo / ".aicr.toml").write_text(
            f'[telemetry]\nenabled = true\nwebhook_url = "{url}"\ninclude_findings = true\n'
        )
        commit("app.py", BAD_PY)
        main(["review", "--repo", str(repo), "--format", "json"])
        assert RECEIVED["body"]["findings"]
    finally:
        srv.shutdown()


def test_unreachable_webhook_does_not_break_the_push(repo, commit):
    (repo / ".aicr.toml").write_text(
        '[telemetry]\nenabled = true\nwebhook_url = "http://127.0.0.1:1"\ntimeout_s = 1\n'
    )
    commit("app.py", GOOD_PY)
    assert main(["review", "--repo", str(repo), "--format", "json"]) == 0
    assert _history_lines()  # local record still happened


def test_env_var_enables_and_overrides_webhook(repo, commit, monkeypatch):
    srv, url = _make_server()
    try:
        monkeypatch.setenv("AICR_TELEMETRY_WEBHOOK", url)
        commit("app.py", GOOD_PY)
        main(["review", "--repo", str(repo), "--format", "json"])
        assert RECEIVED["body"]["source"] == "review"
    finally:
        srv.shutdown()


def test_env_var_format_lets_you_try_card_mode_without_editing_toml(repo, commit, monkeypatch):
    """The scenario this exists for: .aicr.toml already points webhook_url at
    something else (a local dashboard, a different destination); trying card
    mode against a *different* URL should need no file edits at all."""
    srv, url = _make_server()
    try:
        (repo / ".aicr.toml").write_text(
            '[telemetry]\nenabled = true\nwebhook_url = "http://127.0.0.1:1"\n'
        )
        monkeypatch.setenv("AICR_TELEMETRY_WEBHOOK", url)  # overrides the toml's URL
        monkeypatch.setenv("AICR_TELEMETRY_FORMAT", "card")
        commit("app.py", GOOD_PY)
        main(["review", "--repo", str(repo), "--format", "json"])
        assert RECEIVED["body"]["type"] == "AdaptiveCard"
    finally:
        srv.shutdown()


def test_repo_command_tags_source(repo, commit):
    commit("app.py", GOOD_PY)
    main(["repo", "--repo", str(repo), "--format", "json"])
    lines = _history_lines()
    assert lines[-1]["source"] == "repo"


def test_config_error_is_still_recorded(repo, commit, monkeypatch):
    commit("app.py", GOOD_PY)
    monkeypatch.setenv("AICR_PROVIDER", "nope")
    assert main(["review", "--repo", str(repo)]) == 2
    lines = _history_lines()
    assert lines[-1]["error"]
    assert "counts" not in lines[-1]


# --------------------------------------------------------------- doctor --test-webhook

def test_doctor_test_webhook_succeeds_against_live_server(repo):
    srv, url = _make_server()
    try:
        (repo / ".aicr.toml").write_text(
            f'[telemetry]\nenabled = true\nwebhook_url = "{url}"\n'
        )
        assert main(["doctor", "--repo", str(repo), "--test-webhook"]) == 0
        assert RECEIVED["body"]["source"] == "test"
        assert RECEIVED["body"]["test"] is True
    finally:
        srv.shutdown()


def test_doctor_test_webhook_fails_when_unreachable(repo):
    (repo / ".aicr.toml").write_text(
        '[telemetry]\nenabled = true\nwebhook_url = "http://127.0.0.1:1"\ntimeout_s = 1\n'
    )
    assert main(["doctor", "--repo", str(repo), "--test-webhook"]) == 2


def test_doctor_test_webhook_fails_when_disabled(repo):
    (repo / ".aicr.toml").write_text('[telemetry]\nenabled = false\n')
    assert main(["doctor", "--repo", str(repo), "--test-webhook"]) == 2


def test_doctor_without_flag_does_not_touch_webhook(repo):
    srv, url = _make_server()
    try:
        (repo / ".aicr.toml").write_text(
            f'[telemetry]\nenabled = true\nwebhook_url = "{url}"\n'
        )
        main(["doctor", "--repo", str(repo)])
        assert "body" not in RECEIVED
    finally:
        srv.shutdown()


def test_send_test_reports_config_problems_directly():
    from aicr.config import load_config
    cfg = load_config()
    cfg.data["telemetry"] = {"enabled": True, "webhook_url": ""}
    ok, detail = telemetry.send_test(cfg)
    assert ok is False
    assert "webhook_url" in detail


# --------------------------------------------------------------- GitHub remote enrichment

def test_event_has_no_github_fields_without_a_github_remote(repo, commit):
    commit("app.py", GOOD_PY)
    main(["review", "--repo", str(repo), "--format", "json"])
    ev = _history_lines()[-1]
    assert "github_owner" not in ev
    assert "repo_url" not in ev
    assert "branch_url" not in ev


def test_event_includes_github_links_for_a_github_remote(repo, commit):
    from aicr import gitutil
    gitutil.git("config", "remote.origin.url", "https://github.com/acme/widgets.git", cwd=repo)
    commit("app.py", GOOD_PY)
    main(["review", "--repo", str(repo), "--format", "json"])
    ev = _history_lines()[-1]
    assert ev["github_owner"] == "acme"
    assert ev["github_repo"] == "widgets"
    assert ev["repo_url"] == "https://github.com/acme/widgets"
    assert ev["branch_url"] == "https://github.com/acme/widgets/tree/main"


def test_event_includes_user_name_when_it_differs_from_email(repo, commit):
    commit("app.py", GOOD_PY)
    main(["review", "--repo", str(repo), "--format", "json"])
    ev = _history_lines()[-1]
    assert ev["user"] == "dev@example.com"
    assert ev["user_name"] == "Dev"


# --------------------------------------------------------------- telemetry.format = "card"

def _is_valid_adaptive_card(card):
    assert card["type"] == "AdaptiveCard"
    assert card["version"]
    assert isinstance(card["body"], list) and card["body"]
    # Every node in the tree must itself carry a "type" — a structural
    # sanity check for the shape Teams actually deserializes.
    def walk(node):
        if isinstance(node, dict):
            assert "type" in node, node
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)
    walk(card["body"])
    return True


def test_card_format_sends_a_valid_adaptive_card(repo, commit):
    srv, url = _make_server()
    try:
        (repo / ".aicr.toml").write_text(
            f'[telemetry]\nenabled = true\nwebhook_url = "{url}"\nformat = "card"\n'
        )
        commit("app.py", BAD_PY)
        assert main(["review", "--repo", str(repo), "--format", "json"]) == 1
        assert _is_valid_adaptive_card(RECEIVED["body"])
        # Local history must stay the plain event shape regardless of what
        # goes out over the wire — doctor and any other local reader depend on it.
        assert _history_lines()[-1]["source"] == "review"
        assert "type" not in _history_lines()[-1]
    finally:
        srv.shutdown()


def test_card_format_handles_config_errors(repo, commit, monkeypatch):
    (repo / ".aicr.toml").write_text('[telemetry]\nenabled = true\nwebhook_url = "http://127.0.0.1:1"\nformat = "card"\ntimeout_s = 1\n')
    commit("app.py", GOOD_PY)
    monkeypatch.setenv("AICR_PROVIDER", "nope")
    assert main(["review", "--repo", str(repo)]) == 2  # never raises past the webhook layer


def test_card_format_renders_findings_and_github_link(repo, commit):
    srv, url = _make_server()
    try:
        from aicr import gitutil
        gitutil.git("config", "remote.origin.url", "https://github.com/acme/widgets.git", cwd=repo)
        (repo / ".aicr.toml").write_text(
            f'[telemetry]\nenabled = true\nwebhook_url = "{url}"\nformat = "card"\ninclude_findings = true\n'
        )
        commit("app.py", BAD_PY)
        assert main(["review", "--repo", str(repo), "--format", "json"]) == 1
        card = RECEIVED["body"]
        assert _is_valid_adaptive_card(card)
        text = json.dumps(card)
        assert "acme/widgets" in text
        assert "BLOCKED" in text
    finally:
        srv.shutdown()


def test_json_format_is_the_default(repo, commit):
    srv, url = _make_server()
    try:
        (repo / ".aicr.toml").write_text(
            f'[telemetry]\nenabled = true\nwebhook_url = "{url}"\n'
        )
        commit("app.py", GOOD_PY)
        main(["review", "--repo", str(repo), "--format", "json"])
        assert RECEIVED["body"]["source"] == "review"  # unchanged flat shape
        assert "type" not in RECEIVED["body"]
    finally:
        srv.shutdown()
