import json

import pytest

from aicr.engine import dedupe, extract_json, parse_findings
from aicr.models import Finding, ReviewResult


def test_extract_plain_json():
    obj = extract_json('{"summary":"ok","findings":[]}')
    assert obj["summary"] == "ok"


def test_extract_fenced_json():
    raw = 'Sure!\n```json\n{"summary":"s","findings":[]}\n```\nHope that helps.'
    assert extract_json(raw)["summary"] == "s"


def test_extract_json_with_trailing_prose():
    raw = '{"summary":"s","findings":[]} \n\nLet me know if you want more detail.'
    assert extract_json(raw)["findings"] == []


def test_extract_json_with_braces_in_strings():
    raw = '{"summary":"use {} literals","findings":[]}'
    assert "{}" in extract_json(raw)["summary"]


def test_extract_bare_list():
    assert extract_json('[{"title":"x"}]')["findings"][0]["title"] == "x"


def test_extract_empty_response():
    assert extract_json("")["findings"] == []


def test_extract_invalid_raises():
    with pytest.raises(ValueError):
        extract_json("no json at all here")


def test_parse_findings_normalizes_and_maps_paths():
    raw = json.dumps({
        "summary": "one issue",
        "findings": [{
            "file": "./main.py", "line": "42", "severity": "CRITICAL",
            "category": "nonsense", "title": "Secret", "detail": "d",
            "confidence": "sky-high",
        }],
    })
    summary, findings = parse_findings(raw, ["app/main.py"])
    f = findings[0]
    assert summary == "one issue"
    assert f.file == "app/main.py"
    assert f.line == 42
    assert f.severity == "critical"
    assert f.category == "correctness"   # unknown category falls back
    assert f.confidence == "medium"      # unknown confidence falls back


def test_dedupe_keeps_highest_severity():
    a = Finding("a.py", "low", "security", "Same issue", "x", line=3).normalized()
    b = Finding("a.py", "high", "security", "Same issue", "y", line=3).normalized()
    out = dedupe([a, b])
    assert len(out) == 1 and out[0].severity == "high"


def test_blocking_threshold():
    r = ReviewResult(findings=[
        Finding("a.py", "medium", "style", "m", "").normalized(),
        Finding("a.py", "high", "security", "h", "").normalized(),
        Finding("a.py", "critical", "security", "c", "").normalized(),
    ])
    assert len(r.blocking("high")) == 2
    assert len(r.blocking("critical")) == 1
    assert len(r.blocking("medium")) == 3
    assert r.counts()["high"] == 1


def test_sorted_findings_is_severity_first():
    r = ReviewResult(findings=[
        Finding("b.py", "low", "style", "l", "").normalized(),
        Finding("a.py", "critical", "security", "c", "").normalized(),
    ])
    assert r.sorted_findings()[0].severity == "critical"
