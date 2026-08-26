"""Provider wire-format tests against a local HTTP server (no real API calls)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from aicr.providers import available, get_provider
from aicr.providers.base import ConfigError, ProviderError

RECEIVED = {}


def make_server(status: int, body: dict):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", 0))
            RECEIVED["path"] = self.path
            # urllib title-cases header names; compare lowercase.
            RECEIVED["headers"] = {k.lower(): v for k, v in self.headers.items()}
            RECEIVED["body"] = json.loads(self.rfile.read(length) or b"{}")
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):  # silence
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def server():
    created = []

    def _make(status=200, body=None):
        srv = make_server(status, body or {})
        created.append(srv)
        return f"http://127.0.0.1:{srv.server_address[1]}"

    yield _make
    for s in created:
        s.shutdown()


def test_registry_lists_all_providers():
    assert available() == ["anthropic", "gemini", "mock", "ollama", "openai"]


def test_unknown_provider_raises():
    with pytest.raises(ConfigError):
        get_provider("nope", {})


def test_anthropic_request_and_response(server):
    url = server(200, {"content": [{"type": "text", "text": '{"findings":[]}'}]})
    p = get_provider("anthropic", {"base_url": url, "api_key": "k", "model": "m1"})
    assert p.complete("SYS", "USER") == '{"findings":[]}'
    assert RECEIVED["path"] == "/v1/messages"
    assert RECEIVED["headers"]["x-api-key"] == "k"
    assert RECEIVED["headers"]["anthropic-version"]
    assert RECEIVED["body"]["system"] == "SYS"
    assert RECEIVED["body"]["model"] == "m1"
    assert RECEIVED["body"]["temperature"] == 0
    assert RECEIVED["body"]["messages"][0]["content"] == "USER"


def test_anthropic_missing_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    p = get_provider("anthropic", {})
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        p.complete("s", "u")


def test_anthropic_reads_key_from_env(monkeypatch, server):
    monkeypatch.setenv("MY_KEY", "from-env")
    url = server(200, {"content": [{"type": "text", "text": "ok"}]})
    p = get_provider("anthropic", {"base_url": url, "api_key_env": "MY_KEY"})
    p.complete("s", "u")
    assert RECEIVED["headers"]["x-api-key"] == "from-env"


def test_openai_request_and_response(server):
    url = server(200, {"choices": [{"message": {"content": '{"findings":[]}'}}]})
    p = get_provider("openai", {"base_url": url, "api_key": "k", "model": "gpt"})
    assert p.complete("SYS", "USER") == '{"findings":[]}'
    assert RECEIVED["path"] == "/chat/completions"
    assert RECEIVED["headers"]["authorization"] == "Bearer k"
    assert RECEIVED["body"]["messages"][0]["role"] == "system"
    assert RECEIVED["body"]["response_format"]["type"] == "json_object"


def test_ollama_request_and_response(server):
    url = server(200, {"message": {"content": '{"findings":[]}'}})
    p = get_provider("ollama", {"base_url": url, "model": "qwen"})
    assert p.complete("SYS", "USER") == '{"findings":[]}'
    assert RECEIVED["path"] == "/api/chat"
    assert RECEIVED["body"]["stream"] is False
    assert RECEIVED["body"]["format"] == "json"


def test_gemini_request_and_response(server):
    url = server(200, {"candidates": [
        {"content": {"parts": [{"text": '{"findings":[]}'}]}}
    ]})
    p = get_provider("gemini", {"base_url": url, "api_key": "k",
                                "model": "gemini-3.5-flash-lite"})
    assert p.complete("SYS", "USER") == '{"findings":[]}'
    assert RECEIVED["path"] == "/models/gemini-3.5-flash-lite:generateContent"
    assert RECEIVED["headers"]["x-goog-api-key"] == "k"
    assert RECEIVED["body"]["systemInstruction"]["parts"][0]["text"] == "SYS"
    assert RECEIVED["body"]["contents"][0]["parts"][0]["text"] == "USER"
    assert RECEIVED["body"]["generationConfig"]["temperature"] == 0
    assert RECEIVED["body"]["generationConfig"]["responseMimeType"] == "application/json"


def test_gemini_missing_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
        get_provider("gemini", {}).complete("s", "u")


def test_gemini_safety_block_is_config_error(server):
    url = server(200, {"promptFeedback": {"blockReason": "SAFETY"}})
    p = get_provider("gemini", {"base_url": url, "api_key": "k"})
    with pytest.raises(ConfigError, match="blockReason"):
        p.complete("s", "u")


def test_gemini_empty_candidates_returns_empty(server):
    url = server(200, {"candidates": []})
    p = get_provider("gemini", {"base_url": url, "api_key": "k"})
    assert p.complete("s", "u") == ""


def test_auth_failure_is_config_error(server):
    url = server(401, {"error": "bad key"})
    p = get_provider("anthropic", {"base_url": url, "api_key": "bad"})
    with pytest.raises(ConfigError, match="Auth failed"):
        p.complete("s", "u")


def test_server_error_is_provider_error(server):
    url = server(500, {"error": "boom"})
    p = get_provider("openai", {"base_url": url, "api_key": "k"})
    with pytest.raises(ProviderError):
        p.complete("s", "u")


def test_unreachable_host_is_provider_error():
    p = get_provider("ollama", {"base_url": "http://127.0.0.1:1"})
    with pytest.raises(ProviderError, match="Cannot reach"):
        p.complete("s", "u")


def test_mock_provider_flags_known_patterns():
    p = get_provider("mock", {})
    out = json.loads(p.complete("", '=== FILE: a.py ===\n+password = "abcdefghij"\n'))
    assert out["findings"][0]["severity"] == "critical"
    assert out["findings"][0]["file"] == "a.py"
