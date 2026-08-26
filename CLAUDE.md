# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

`aicr` is a local AI code-review gate. It installs a git `pre-push` hook that reviews
the diff a developer is about to push and **blocks the push** when it finds a
`critical` or `high` severity issue. It runs entirely on the developer's machine —
there is no server, no CI job, and no GitHub App.

The user is a team of 10–14 developers with one overloaded reviewer. The design goal
is that the manager stops being the first reviewer. Every decision should be weighed
against one question: **does this make a developer more or less likely to disable the
tool?** A gate that annoys people gets bypassed with `--no-verify`, and then it
protects nothing.

## Commands

```bash
pip install -e '.[dev]'          # dev install
pytest                           # full suite, ~10s, no network, no API key
pytest tests/test_engine.py -k cache -x
PYTHONPATH=src python3 -m aicr review   # run without installing

AICR_PROVIDER=mock aicr review   # offline regex reviewer — use this for manual testing
AICR_PROVIDER=mock aicr doctor

python3 samples/run-smoke.py --provider gemini   # does this model reach the right verdicts?
```

There is no linter or formatter configured. Match the surrounding style.

## Architecture

```
cli.py          argparse commands, exit codes, output selection
  ├─ config.py      layered config (defaults → ~/.config → .aicr.toml → .local → env)
  ├─ gitutil.py     git plumbing; resolves WHICH commits are being pushed
  ├─ chunker.py     splits a unified diff per file, bin-packs into batches
  ├─ engine.py      orchestration, JSON extraction, dedupe, caching, concurrency
  │    ├─ prompts.py    the system prompt — this is where review quality lives
  │    └─ providers/    anthropic | openai | gemini | ollama | mock
  ├─ report/        terminal + markdown renderers
  ├─ hookinstall.py writes/removes .git/hooks/pre-push
  └─ cursorinit.py  writes .cursor/hooks.json + .cursor/commands/*.md

samples/        10 fixtures with known verdicts (4 must block, 6 must pass)
  └─ run-smoke.py   checks a provider/model reaches the right verdict on each
docs/           ROLLOUT.md, TOOL-COMPARISON.md, the one-pager PDF + its generator
```

Data flow for a push: `pre-push` stdin lines → `resolve_push_range` → `git diff` →
`split_diff` → filter excluded/binary → `pack` into chunks → parallel
`provider.complete` → `parse_findings` → `dedupe` → `ReviewResult.blocking(fail_on)`
→ exit code.

## Hard constraints

**Stdlib only at runtime.** The single runtime dependency is `tomli`, and only on
Python < 3.11. HTTP goes through `urllib` in `providers/base.py:http_json`. Do not add
`requests`, `httpx`, `pydantic`, `rich`, or any provider SDK. Every dependency is
something 14 developers have to install successfully before this tool does anything,
and a failed install is a disabled reviewer. `pytest` as a dev extra is fine.

This is not stylistic minimalism: PR-Agent, the closest comparable tool, has **40
direct runtime dependencies** with pinned `==` versions — boto3,
google-cloud-aiplatform, azure-devops, fastapi, uvicorn, gunicorn, litellm, and
`pytest` as a *runtime* dep — and requires Python 3.12+. That is a fine trade for
a CI-hosted PR bot. It is a bad trade for something 14 developers install on 14
laptops. Anything that moves aicr toward that shape is a regression, however
useful the feature. (Verified hands-on during evaluation, not just from PR-Agent's
own metadata — see `docs/TOOL-COMPARISON.md`.)

**Python 3.9+.** No `match`, no `X | Y` type syntax at runtime, no `tomllib` without
the `tomli` fallback already in `config.py`.

**The hook must never crash a push.** `cmd_pre_push` returns `EXIT_OK` when it cannot
find the repo, when there is nothing to review, and when everything is excluded.
A traceback reaching the developer's terminal during `git push` is a bug, regardless
of cause.

**`fail_open` applies to outages, not misconfiguration.** This distinction is
deliberate and there is a test pinning it
(`test_missing_api_key_does_not_silently_pass`):

- `ProviderError` (network down, 500, timeout) + `fail_open=true` → exit 0, push
  proceeds. An outage must not block the team.
- `ConfigError` (missing API key, unknown provider, 401) → exit 2 always. A
  misconfigured reviewer that reports "passed" is worse than no reviewer, because it
  quietly stops reviewing while everyone believes it is working.

**Exit codes are a contract.** `0` clean · `1` blocking findings · `2` config/tool
error. The hook, the tests, and anyone scripting around this depend on these.

**`cursor-hook` has a different contract from every other command.** It speaks
Cursor's `beforeShellExecution` protocol: JSON in on stdin, JSON out on stdout,
and it must ALWAYS print valid JSON and exit `0`. A non-zero exit or malformed
output means Cursor either blocks every shell command the agent runs or silently
ignores the gate. It therefore catches `Exception` broadly and degrades to
`{"permission": "allow"}` — the one place in this codebase where a bare except is
correct. Its verdict lives in the JSON body, never in the exit code.

## Where to change what

| Goal | Edit |
|---|---|
| Review quality, what gets flagged, severity calibration | `prompts.py` (`SYSTEM`) |
| Team-specific rules | `custom_rules` in the repo's `.aicr.toml`, not code |
| New LLM backend | new class in `providers/`, register in `providers/__init__.py` |
| What blocks a push | `fail_on` config, or `ReviewResult.blocking` |
| Files never reviewed | `exclude` in `config.py:DEFAULTS` |

**Tune the prompt before touching code.** Most "the reviewer is wrong" reports are
prompt or `custom_rules` problems, not bugs. The `SYSTEM` prompt's HARD RULES section
exists to suppress noise — nitpicking about formatting is explicitly forbidden there,
because that is the fastest way to get the tool uninstalled.

Adding a provider means implementing one method:

```python
class MyProvider(Provider):
    name = "myprovider"
    def complete(self, system: str, user: str) -> str: ...   # returns raw text
```

Raise `ConfigError` for missing keys, let `http_json` raise `ProviderError` for
transport failures, and add defaults under a `[myprovider]` table in
`config.py:DEFAULTS`.

## Testing conventions

- **No network, no API keys, ever.** `tests/test_providers.py` runs a real
  `HTTPServer` on `127.0.0.1` and asserts the exact request body and headers each
  provider sends. Extend that pattern rather than mocking `urllib`.
- **The `mock` provider is production code, not a test fixture.** It lives in
  `providers/mock_provider.py` and flags a handful of patterns with regex so the whole
  pipeline is exercisable offline. Keep it working.
- **`tests/test_hook_e2e.py` really runs `git push`** against a bare repo in `tmp_path`
  and asserts it is refused. If you change hook wiring, exit codes, or push-range
  resolution, this is the test that catches you. It installs a shim hook pointing at
  `sys.executable` so it does not need `aicr` on `PATH`.
- The `repo` and `commit` fixtures in `conftest.py` give you a git repo with an
  `origin` remote and one commit on `main`.
- When adding a config option, add a test that it actually changes behaviour —
  several options are only reachable through `Reviewer`, so a typo in the key name
  fails silently.

**`samples/` is a different kind of test and `pytest` does not touch it.** The
unit suite proves the pipeline works; `samples/run-smoke.py` proves a given
*model* reviews well, which no amount of mocking can tell you. Run it against a
real provider after changing `prompts.py` — that is the only way to find out
whether a prompt edit helped or just moved the false positives around.

The six `good_*` fixtures matter more than the four `bad_*` ones. They are
written to bait a trigger-happy reviewer: raw-looking SQL that is parameterized,
a crypto comparison that is constant-time, `rm`-adjacent shell that is guarded,
shared mutable state that is mutex-held. **A false positive on a `good_` file is
a worse outcome than a miss on a `bad_` one**, because that is what makes people
reach for `--no-verify`. Tune for that asymmetry.

`bad_03_orders.py` is the difficulty gauge: N+1, unbounded query, check-then-act
race, missing timeout. Pattern matching cannot find those. The `mock` provider
fails exactly this one file, which is the expected result.

## Gotchas

**Push-range resolution is the subtlest part of the codebase.**
`gitutil.resolve_push_range` handles: normal push (`remote_sha..local_sha`), new
branch with no remote counterpart (merge-base against the default branch), branch
deletion (returns `None`), and the case where the remote sha is not present locally.
Getting this wrong means reviewing all of history on a new branch — slow, expensive,
and full of false positives about code nobody touched. Test changes here against a
new branch specifically.

**Hooks are per-clone and bypassable.** `.git/hooks` is not version controlled and
`--no-verify` skips it. The tool cannot log a bypass, because the hook does not run.
Do not add code that claims otherwise or pretends to enforce something it cannot; the
README and `docs/ROLLOUT.md` are deliberately honest about this. Server-side
enforcement is the documented next step.

**The hook uses an absolute path to `aicr`.** `hookinstall.resolve_aicr_bin` resolves
it at install time so GUI git clients (Tower, GitHub Desktop, VS Code), which do not
load the user's shell profile, still find the binary. Keep the `command -v` fallback.

**Models do not reliably return bare JSON.** `engine.extract_json` handles code
fences, leading prose, trailing prose, bare arrays, and braces inside strings via a
depth-counting scan. Weaker local models make this matter. Add a test case here before
"simplifying" it to `json.loads`.

**Cache keys include the prompt inputs.** `_cache_key` hashes provider, model,
`project_context`, `custom_rules`, and the diff body, so editing `.aicr.toml`
correctly invalidates cached reviews. If you add anything that changes review output,
add it to that key or bump `CACHE_VERSION`.

**Whole-file mode vs diff mode** produce different input formats — numbered lines
(`   12 | code`) versus `+`/`-` diff lines — and `prompts.py` swaps the reading
instructions accordingly. Anything parsing the review body must handle both.

## Style

Type hints on public functions. Docstrings on modules and non-obvious functions only;
skip them where the signature says everything. Errors reaching a developer should say
what to do next, not just what failed — see the `ConfigError` messages in
`anthropic_provider.py` for the intended tone.
