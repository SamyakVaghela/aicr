# aicr — AI code review before every push

A local code-review gate. It runs on each developer's machine, reviews the code they
are about to push, and **blocks `git push`** when it finds a critical or high-severity
problem. Nothing is deployed to a server; there is no CI job and no GitHub App.

The point is that the manager stops being the first reviewer. By the time a pull
request opens, the obvious security holes, injection bugs, N+1 queries, and swallowed
exceptions are already gone.

```
────────────────────────────────────────────────────────────────
 AI CODE REVIEW  ·  anthropic/claude-sonnet-5
 3 file(s) · 11.4s
────────────────────────────────────────────────────────────────

 CRITICAL   Hardcoded credential
            api/settings.py:14  ·  security  ·  BLOCKS PUSH
            A live API key is committed in source. Anyone with repo
            access, now or in the future, can read it.
            Fix:
            API_KEY = os.environ["STRIPE_API_KEY"]

 HIGH       SQL built with string interpolation
            api/users.py:88  ·  security  ·  BLOCKS PUSH
            ...

────────────────────────────────────────────────────────────────
 1 critical, 2 high, 1 medium

 ✗  PUSH BLOCKED — 3 issue(s) at 'high' or above must be fixed.
```

---

## How it works

```
 git push
    │
    ▼
 .git/hooks/pre-push  ──►  aicr pre-push
                              │
                              ├─ work out exactly which commits are being pushed
                              ├─ git diff that range  (any language)
                              ├─ drop binaries, lockfiles, vendored code
                              ├─ split into batches, review them in parallel
                              ├─ send to Claude / OpenAI / local Ollama
                              └─ exit 1 if any finding is >= fail_on
    │
    ├── exit 0 ──► push proceeds
    └── exit 1 ──► push refused, findings printed
```

Language-agnostic by design: the reviewer is a prompt, not a parser. Python, JS/TS,
Go, Java, C#, Ruby, PHP, Rust, SQL, shell, Terraform, YAML, Dockerfiles — anything in
the diff gets reviewed.

## Install (each developer, once)

```bash
git clone <this-repo> ~/tools/aicr        # or however you distribute it
cd ~/your-project
~/tools/aicr/scripts/setup-dev.sh
```

That installs the `aicr` command (pipx if present, otherwise a venv at `~/.aicr-venv`),
installs the pre-push hook in the current repo, and runs `aicr doctor`.

Then set the API key for whichever provider your team picked:

```bash
echo 'export ANTHROPIC_API_KEY=sk-ant-...' >> ~/.zshrc && source ~/.zshrc
```

Manual equivalent:

```bash
pipx install ~/tools/aicr
cd ~/your-project && aicr install-hook && aicr doctor
```

Repeat `aicr install-hook` once per repo per clone — git hooks live in `.git/`, which
is not shared. `aicr install-hook --shared` gets this down to one generic `git
config` command per teammate instead (see `docs/ROLLOUT.md`) — git fundamentally
requires *some* action per clone, by design, so this is as close to automatic as
it gets without opening a supply-chain hole.

## Configure (once per repo, by you)

```bash
cd ~/your-project
aicr init          # writes .aicr.toml and adds .aicr.local.toml to .gitignore
```

Then edit `.aicr.toml` and commit it. The two fields that matter most:

```toml
project_context = """
Django 4 REST API + React 18 frontend. Postgres 15. Deployed on AWS ECS.
All DB access goes through the repository layer in app/repositories/.
"""

custom_rules = [
  "No secrets, API keys, or passwords in source or config.",
  "All new endpoints must validate and sanitize user input.",
  "No raw SQL string interpolation — use the ORM or parameterized queries.",
  "Migrations must be backwards compatible with the running release.",
  "New business logic needs at least one accompanying test.",
]
```

A rule violation is reported at `medium` or above. This is where you encode the
things your manager keeps repeating in review comments.

## Commands

| Command | What it does |
|---|---|
| `aicr review` | Review what you are about to push (default) |
| `aicr review --staged` | Review staged changes before committing |
| `aicr review --working` | Review uncommitted work in progress |
| `aicr review --range main..HEAD` | Review any git range |
| `aicr review --files a.py b.js` | Review whole files, not a diff |
| `aicr repo` | Review the entire tracked repository |
| `aicr repo --path src/api` | Review one directory in full |
| `aicr doctor` | Check config, hook, API key, connectivity |
| `aicr init` | Create `.aicr.toml` |
| `aicr install-hook` | Install the blocking pre-push hook |
| `aicr install-hook --shared` | Same, but committed to `.githooks/` — teammates need one `git config` line instead |
| `aicr uninstall-hook` | Remove it |
| `aicr cursor-init` | Install the Cursor IDE integration (see below) |
| `aicr github-init` | Install the GitHub Actions PR-comment workflow (see below) |

Useful flags on any review command: `--format markdown|json`, `--out report.md`,
`--fail-on critical`, `--provider ollama`, `--model ...`, `--no-cache`, `-v`.

```bash
# Generate a markdown report to paste into the PR description
aicr review --format markdown --out review.md

# Machine-readable, for scripting
aicr review --format json | jq '.findings[] | select(.severity=="critical")'
```

Exit codes: `0` clean, `1` blocking issues found, `2` configuration or tool error.

## Cursor IDE

`aicr` is a CLI and a git hook, not a Cursor extension — so it works in Cursor
without installing anything into the editor. There are three surfaces, and
`aicr cursor-init` wires up the two that are Cursor-specific:

| Surface | Fires when | Set up by |
|---|---|---|
| **Git pre-push hook** | Any `git push` — integrated terminal, Source Control panel, external terminal, another IDE | `aicr install-hook` |
| **Cursor agent gate** | The Cursor agent tries to run `git push` | `aicr cursor-init` |
| **`/aicr-review`, `/aicr-fix`** | You type `/` in Cursor chat | `aicr cursor-init` |

```bash
aicr install-hook     # per clone, not committed
aicr cursor-init      # writes .cursor/ — commit this
git add .cursor && git commit -m "Add aicr Cursor integration"
```

**The agent gate is the interesting one.** It is a `beforeShellExecution` hook
in `.cursor/hooks.json`. When the agent tries to push, aicr reviews the diff
and can return `deny` with the findings attached as `agent_message` — so the
agent *reads the review and fixes the code itself*, then pushes again. The
message explicitly tells it not to retry with `--no-verify` or lower
`fail_on`, because otherwise a capable agent will happily route around the
gate it just hit.

Project hooks live in `.cursor/hooks.json`, are committed, and load
automatically for anyone who opens the repo in a trusted workspace. That is
the one part of this that is genuinely team-wide without an Enterprise plan —
Cursor's own Agent Review setting is per-developer and cannot be enforced.

**Slash commands** are markdown prompts in `.cursor/commands/`:

- `/aicr-review` — run a review, summarise findings, propose fixes, change nothing
- `/aicr-fix` — run a review and fix every blocking finding

**GUI pushes.** When you push from Cursor's Source Control panel rather than a
terminal, Cursor swallows hook output into a log channel nobody reads and shows
a generic failure toast. So when a push is blocked, aicr also writes the full
report to `.aicr-review.md` in the repo root (gitignored) — open that to see
what happened. Change the location with `report_path`.

Not using Cursor? Everything except `cursor-init` works identically anywhere.

## GitHub Actions (review on the PR itself)

The local hook only reaches developers who installed it and didn't push with
`--no-verify`. `aicr github-init` writes the CI companion:
`.github/workflows/aicr-review.yml`. It runs on every push to a pull request,
reviews the PR's diff, and posts (or updates) one comment on the PR with the
findings — visible next to the code, for anyone with access to the PR, no
`aicr` install required to read it.

```bash
aicr github-init
git add .github && git commit -m "Add aicr PR review workflow"
```

Edit the "Install aicr" step first — point it at wherever your org hosts
`aicr` (it isn't on the public PyPI). It picks up `ANTHROPIC_API_KEY` /
`OPENAI_API_KEY` / `GEMINI_API_KEY` from repo secrets, whichever matches your
configured provider.

By default this workflow **only comments — it never fails the check or blocks
merging.** That's deliberate: it's visibility, not a second gate, and it runs
without asking anyone to change how they work. If you later want unavoidable
enforcement (something `--no-verify` can't skip, unlike the local hook), the
file has a one-line change called out to make it a required status check —
same idea as the "server-side check" mentioned in
[Bypassing](#bypassing), just landed.

## Configuration reference

Settings merge in this order, later wins:

1. built-in defaults
2. `~/.config/aicr/config.toml` — personal machine defaults
3. `<repo>/.aicr.toml` — team settings, **committed**
4. `<repo>/.aicr.local.toml` — personal per-repo overrides, gitignored
5. `AICR_*` environment variables

| Key | Default | Meaning |
|---|---|---|
| `provider` | `anthropic` | `anthropic`, `openai`, `gemini`, `ollama`, `mock` |
| `fail_on` | `high` | Block the push at this severity and above |
| `fail_open` | `true` | If the provider is unreachable, allow the push |
| `max_files` | `60` | Cap on files per review |
| `max_diff_bytes` | `400000` | Cap on total diff size |
| `chunk_bytes` | `45000` | Batch size sent per request |
| `context_lines` | `5` | Diff context given to the model |
| `concurrency` | `4` | Batches reviewed in parallel |
| `timeout_s` | `120` | Per-request timeout |
| `cache` | `true` | Skip re-reviewing an unchanged diff |
| `report_path` | `.aicr-review.md` | Where to write the report when a push is blocked |
| `exclude` | lockfiles, `node_modules`, `dist`, images, … | Glob patterns to skip |
| `project_context` | `""` | Free text about the codebase |
| `custom_rules` | `[]` | Team rules the reviewer must enforce |
| `telemetry.enabled` | `false` | Report each review to `telemetry.webhook_url` (see [Visibility for admins](#visibility-for-admins)) |
| `telemetry.webhook_url` | `""` | Where to POST review events |
| `telemetry.include_findings` | `false` | Include finding text (not just counts) in the event |

Env overrides: `AICR_PROVIDER`, `AICR_MODEL`, `AICR_FAIL_ON`, `AICR_FAIL_OPEN`,
`AICR_CONCURRENCY`, `AICR_TIMEOUT`, `AICR_CACHE`, `AICR_MAX_FILES`, `AICR_DISABLE=1`,
`AICR_TELEMETRY_WEBHOOK` (also flips `telemetry.enabled` on).

### Providers

```toml
[anthropic]                        # default
model = "claude-sonnet-5"
api_key_env = "ANTHROPIC_API_KEY"

[openai]                           # also works with any OpenAI-compatible gateway
model = "gpt-4.1"
api_key_env = "OPENAI_API_KEY"
base_url = "https://api.openai.com/v1"

[gemini]                           # cheapest hosted option
model = "gemini-3.5-flash-lite"
api_key_env = "GEMINI_API_KEY"

[ollama]                           # fully local, no code leaves the machine
model = "qwen2.5-coder:14b"
base_url = "http://localhost:11434"
```

> **Gemini free tier warning.** Google states that on the **free** tier your
> prompts and responses are used to improve their products — for this tool, that
> means your source code. Enable billing on the API key before pointing it at a
> company codebase. Paid Gemini runs roughly a cent per review, so the whole
> team costs a few dollars a month; there is no real reason to take the free
> tier's terms.

Switch for one run without editing anything: `aicr review --provider ollama`.

## Severity model

| Severity | Meaning | Default |
|---|---|---|
| `critical` | Exploitable security hole, data loss, committed secret | **blocks** |
| `high` | Real bug or weakness likely to cause an incident | **blocks** |
| `medium` | Genuine problem worth fixing before merge | warns |
| `low` | Minor issue or cleanup | warns |
| `info` | Observation | warns |

Formatting, import order, and line length are explicitly out of scope — that is your
linter's job, and nagging about it is how a tool like this gets disabled.

## Bypassing

```bash
git push --no-verify        # skip all hooks
AICR_DISABLE=1 git push     # skip just this reviewer
```

Both are intentional escape hatches for an outage or a hotfix at 2am. Note that
neither can be logged by the tool itself — `--no-verify` prevents the hook from
running at all. Treat the gate as a strong default, not a security control; a
server-side check is the only way to make it unavoidable, and that is the natural
next step once the team is happy with the reviews.

## Visibility for admins

Off by default. Turn it on and every review run — the pre-push gate, plus `aicr
review` and `aicr repo` run by hand — records one event: who, when, which repo and
branch, provider/model, how many findings at each severity, and whether the push
was blocked. Two independent places it can land:

- **Locally, always.** Every developer's machine keeps its own log at
  `~/.config/aicr/history.jsonl` (`$XDG_CONFIG_HOME/aicr/history.jsonl` if set),
  regardless of the `telemetry` config. `aicr doctor` prints the path.
- **A webhook, opt-in.** Set `telemetry.enabled = true` and `telemetry.webhook_url`
  and each event is also POSTed there as JSON — point it at a Slack incoming
  webhook, or your own endpoint. Finding text is left out by default (only
  severity counts go out); set `telemetry.include_findings = true` to send it.
  A broken or slow webhook never blocks or delays the push beyond its
  `telemetry.timeout_s` (default 4s, no retries).

```toml
# .aicr.toml
[telemetry]
enabled = true
webhook_url = "https://hooks.slack.com/services/…"
```

Prefer setting `AICR_TELEMETRY_WEBHOOK` in each developer's shell (or in your
bootstrap script) over committing the URL to `.aicr.toml` — it behaves like a
credential, and the env var takes priority over config.

**Verify a new webhook before relying on it:**

```bash
aicr doctor --test-webhook
```

Sends one synthetic event (`"source": "test"`, `"blocked": false`) to
`telemetry.webhook_url` and reports whether it actually arrived — so setting
up a new destination (a Slack channel, a Teams channel via a Workflow, your
own endpoint) is a one-command check, not a wait-for-the-next-real-push guess.
Exits `0` on delivery, `2` with the reason otherwise (unreachable, timed out,
non-2xx, or `telemetry.enabled` is off).

**Read this as an activity feed, not an audit log.** The [Bypassing](#bypassing)
section above still applies here: `git push --no-verify` means the hook never
runs, so nothing is recorded — there is no way for a local tool to distinguish
"didn't push" from "pushed around the gate." If you need to *prove* every push
was reviewed, that requires a check the developer cannot skip — branch
protection / a required status check on your git host — which is the same
server-side step called out above, not something this local tool can do on its
own.

## Cost and speed

A typical 200-line change is one request: a few seconds and well under a cent on
Claude Sonnet. Identical diffs are cached in `.git/aicr-cache`, so re-pushing after a
rebase with no code change costs nothing. A whole-repo `aicr repo` run on a large
codebase is the expensive case — run it deliberately, not in a hook.

For a team of 10–14 devs, budget roughly a few dollars a day. Ollama makes it free at
the cost of review quality.

## Privacy

Diffs are sent to whichever provider you configure. If your code cannot leave your
network, use `provider = "ollama"` — reviews then run entirely on the developer's
machine. No provider here trains on API data by default, but confirm that against
your own agreement before rolling out.

## Checking a model before you roll it out

`samples/` holds ten files with known-correct verdicts — four that must be
blocked, six that must pass — across Python, JS, TS, Go, and Bash.

```bash
python3 samples/run-smoke.py --provider gemini
```

It reviews each file in a throwaway repo and prints a pass/fail table. Use it
to compare models before committing the team to one. The six clean files are
the important half: a reviewer that flags those is one your developers will
start bypassing. See `samples/README.md`.

## Development

```bash
pip install -e '.[dev]'
pytest                      # 91 tests, no network, no API key needed
AICR_PROVIDER=mock aicr review   # offline regex-based fake reviewer
```

The `mock` provider makes the whole pipeline testable offline. The end-to-end tests
really do run `git push` against a temp remote and assert that it is refused; the
provider tests run a local HTTP server and assert the exact request shape sent to
Anthropic, OpenAI, Gemini, and Ollama.

## Layout

```
src/aicr/
  cli.py            commands and exit codes
  config.py         layered config loading
  gitutil.py        git plumbing, push-range resolution
  chunker.py        diff splitting and batching
  engine.py         review orchestration, JSON parsing, caching
  prompts.py        the review prompt (edit this to tune behaviour)
  models.py         Finding / ReviewResult, severity model
  hookinstall.py    pre-push hook install / uninstall
  providers/        anthropic, openai, gemini, ollama, mock
  cursorinit.py     Cursor .cursor/hooks.json + slash commands
  report/           terminal and markdown renderers
scripts/setup-dev.sh   one-command developer setup
docs/ROLLOUT.md        how to roll this out to the team
```

Tuning review behaviour is mostly editing `prompts.py` and `custom_rules`.
