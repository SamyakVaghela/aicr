import json

import pytest

from aicr.chunker import FileDiff
from aicr.config import load_config
from aicr.engine import Reviewer
from aicr.providers.base import Provider, ProviderError


class ScriptedProvider(Provider):
    """Returns canned responses in order; records the prompts it received."""

    name = "scripted"

    def __init__(self, responses, cfg=None):
        super().__init__(cfg or {"model": "test"})
        self.responses = list(responses)
        self.prompts = []

    def complete(self, system, user):
        self.prompts.append(user)
        r = self.responses.pop(0) if self.responses else '{"summary":"","findings":[]}'
        if isinstance(r, Exception):
            raise r
        return r


def _cfg(repo, **over):
    cfg = load_config(repo)
    cfg.data["cache"] = False
    cfg.data.update(over)
    return cfg


def test_review_returns_findings(repo):
    resp = json.dumps({"summary": "one bug", "findings": [
        {"file": "app.py", "line": 3, "severity": "high", "category": "security",
         "title": "SQL injection", "detail": "interpolated query", "confidence": "high"},
    ]})
    rv = Reviewer(_cfg(repo), repo, provider=ScriptedProvider([resp]))
    result = rv.review([FileDiff(path="app.py", text="+q = f'select {x}'\n")])
    assert len(result.findings) == 1
    assert result.findings[0].severity == "high"
    assert result.blocking("high")
    assert not result.blocking("critical")
    assert result.summary == "one bug"


def test_clean_diff_passes(repo):
    rv = Reviewer(_cfg(repo), repo,
                  provider=ScriptedProvider(['{"summary":"looks good","findings":[]}']))
    result = rv.review([FileDiff(path="app.py", text="+x = 1\n")])
    assert result.findings == []
    assert result.blocking("high") == []


def test_empty_input_short_circuits(repo):
    provider = ScriptedProvider([])
    result = Reviewer(_cfg(repo), repo, provider=provider).review([])
    assert result.summary == "No reviewable changes."
    assert provider.prompts == []


def test_provider_error_is_captured_not_raised(repo):
    rv = Reviewer(_cfg(repo), repo, provider=ScriptedProvider([ProviderError("boom")]))
    result = rv.review([FileDiff(path="a.py", text="+x=1\n")])
    assert result.errors and "boom" in result.errors[0]
    assert result.findings == []


def test_bad_json_recorded_as_error(repo):
    rv = Reviewer(_cfg(repo), repo, provider=ScriptedProvider(["totally not json"]))
    result = rv.review([FileDiff(path="a.py", text="+x=1\n")])
    assert result.errors and "parse" in result.errors[0].lower()


def test_multiple_chunks_are_merged(repo):
    r1 = json.dumps({"summary": "a", "findings": [
        {"file": "a.py", "severity": "medium", "category": "correctness",
         "title": "issue A", "detail": "d"}]})
    r2 = json.dumps({"summary": "b", "findings": [
        {"file": "b.py", "severity": "critical", "category": "security",
         "title": "issue B", "detail": "d"}]})
    cfg = _cfg(repo, chunk_bytes=50, concurrency=2)
    provider = ScriptedProvider([r1, r2])
    files = [FileDiff(path="a.py", text="+" + "x" * 60),
             FileDiff(path="b.py", text="+" + "y" * 60)]
    result = Reviewer(cfg, repo, provider=provider).review(files)
    assert len(provider.prompts) == 2
    assert {f.title for f in result.findings} == {"issue A", "issue B"}
    assert result.sorted_findings()[0].severity == "critical"


def test_custom_rules_reach_the_prompt(repo):
    cfg = _cfg(repo, custom_rules=["No print statements in production code"],
               project_context="Django API")
    provider = ScriptedProvider(['{"summary":"","findings":[]}'])
    Reviewer(cfg, repo, provider=provider).review([FileDiff(path="a.py", text="+x=1\n")])
    prompt = provider.prompts[0]
    assert "No print statements in production code" in prompt
    assert "Django API" in prompt


def test_excluded_files_are_dropped(repo):
    diff = (
        "diff --git a/yarn.lock b/yarn.lock\n--- a/yarn.lock\n+++ b/yarn.lock\n@@ -1 +1,2 @@\n+dep\n"
        "diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n@@ -1 +1,2 @@\n+x=1\n"
    )
    rv = Reviewer(_cfg(repo), repo, provider=ScriptedProvider([]))
    files, skipped = rv.files_from_diff(diff)
    assert [f.path for f in files] == ["src/a.py"]
    assert any("yarn.lock" in s for s in skipped)


def test_max_files_cap(repo):
    diffs = "".join(
        f"diff --git a/f{i}.py b/f{i}.py\n--- a/f{i}.py\n+++ b/f{i}.py\n@@ -1 +1,2 @@\n+x={i}\n"
        for i in range(10)
    )
    rv = Reviewer(_cfg(repo, max_files=3), repo, provider=ScriptedProvider([]))
    files, skipped = rv.files_from_diff(diffs)
    assert len(files) == 3
    assert sum("max_files" in s for s in skipped) == 7


def test_whole_file_mode_numbers_lines(repo, commit):
    commit("src/app.py", "alpha\nbeta\n")
    rv = Reviewer(_cfg(repo), repo, provider=ScriptedProvider([]))
    files, _ = rv.files_from_paths(["src/app.py"])
    assert "    1 | alpha" in files[0].text


def test_cache_prevents_second_call(repo):
    cfg = _cfg(repo)
    cfg.data["cache"] = True
    files = [FileDiff(path="a.py", text="+x=1\n")]
    p1 = ScriptedProvider(['{"summary":"cached","findings":[]}'])
    Reviewer(cfg, repo, provider=p1).review(files)
    p2 = ScriptedProvider([])
    result = Reviewer(cfg, repo, provider=p2).review(files)
    assert p2.prompts == []
    assert result.from_cache
    assert result.summary == "cached"
