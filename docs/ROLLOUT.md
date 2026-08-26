# Rolling this out to the team

Written for a team of 10–14 developers with one overloaded reviewer. The goal is
that the manager sees fewer, cleaner pull requests — not that developers feel
policed.

## The honest constraint up front

Git hooks live in `.git/hooks/`, which is **not** version-controlled and **not**
cloned. That has two consequences you should decide about before announcing this:

1. Every developer must install the hook once per clone.
2. Anyone can bypass it with `git push --no-verify`.

So this is a strong default, not an enforcement boundary. It works because the
review is useful and fast, not because it is impossible to skip. If you need
something genuinely unavoidable later, the answer is a server-side check (a GitHub
Action running `aicr review --range` on the PR, or a required status check) — the
same tool, same config, run where developers cannot skip it. Nothing here has to be
rewritten for that.

Two things make the local gate much stickier in the meantime:

**Point `core.hooksPath` at a committed directory.** Then the hook itself is in the
repo and a new clone only needs one config command:

```bash
# once, by you
aicr install-hook --shared
git add .githooks && git commit -m "Add shared git hooks"

# once per developer per clone
git config core.hooksPath .githooks
```

`--shared` writes to `.githooks/` instead of `.git/hooks/`, points *your* clone's
`core.hooksPath` at it immediately, and prints the one line above for everyone
else. It deliberately relies only on `command -v aicr` rather than baking in an
absolute path the way the default `install-hook` does — appropriate here since
this script is shared verbatim across everyone's machine, not tailored to yours
— which does mean it trades away the extra robustness the default install gives
GUI git clients (Tower, GitHub Desktop) with a restricted PATH. Use the default
`aicr install-hook` per developer instead if that matters more to your team than
the one-command onboarding.

**Or wire it into your existing bootstrap.** If the team already runs `make setup`
or `npm install`, add the hook install there and nobody has to remember anything.

## Week 1 — advisory only

Run it without teeth so people see the value before they feel the friction.

```toml
# .aicr.toml
fail_on = "critical"   # almost nothing blocks
fail_open = true
```

Ask each developer to run `scripts/setup-dev.sh`, then just let it print findings
for a week. Collect the false positives — that is your tuning input.

## Week 2 — tune

Two levers, in this order:

1. **`custom_rules` in `.aicr.toml`.** This is where the real gains are. Write down
   the comments your manager leaves over and over. Six to twelve specific rules
   beats fifty vague ones.
2. **`prompts.py`.** If the reviewer keeps flagging a category you do not care
   about, say so explicitly in the "HARD RULES" section of the system prompt.

Signs you have tuned too loose: reviews come back empty on changes that later get
review comments. Too tight: developers start reflexively using `--no-verify`. Watch
for the second one — it is the failure mode that kills tools like this.

## Week 3 — turn on the gate

```toml
fail_on = "high"       # critical + high block the push
```

Announce it with the bypass documented in the same message. A gate people know how
to escape gets used; a gate that traps them gets uninstalled.

## Provider choice

| | Anthropic / OpenAI | Ollama (local) |
|---|---|---|
| Review quality | Good enough to catch real bugs | Noticeably weaker, more false positives |
| Cost | ~a few dollars/day for 10–14 devs | Free |
| Code leaves the machine | Yes, to the API | No |
| Setup per developer | One API key | Install Ollama, pull a ~9GB model |

Start with a hosted model. Consider Ollama if legal or client contracts require
that code never leaves the machine.

### API keys

Simplest: each developer uses their own key, exported in their shell profile.
Costs land on individual accounts, which is usually not what you want.

Better: one organization account, keys issued per developer so you can see usage
and revoke individually. Set a monthly spend cap on the account — that is your
protection against someone looping `aicr repo` on a large codebase.

Do **not** commit a shared key to `.aicr.toml`. The config supports `api_key_env`
precisely so the key stays out of the repo. (The reviewer will flag you for it.)

## Seeing who's actually running it

Turn on `[telemetry]` in `.aicr.toml` (see the README's "Visibility for admins")
and every review — pre-push and manual — reports its counts and pass/fail to a
webhook you point it at (a Slack channel is the low-effort choice). That answers
"is the team using this" for the reviews that ran.

It cannot answer "did everyone review every push" — `--no-verify` skips the hook
entirely, so a bypassed push leaves nothing to report. If a name never shows up
in the feed, that is a conversation ("is the hook installed? doctor says what?"),
not proof of anything stronger. Genuine, unavoidable enforcement is the
server-side check mentioned above — required status checks on the git host — and
that is the only thing that actually closes this gap.

## Measuring whether it worked

Before you turn the gate on, note your baseline for a couple of weeks:

- review comments per PR from the manager
- time from PR open to first review
- number of PRs needing a second round of changes

If it is working, the first two drop noticeably within a month. If they do not,
the problem is almost certainly `custom_rules` being too generic — the reviewer is
finding textbook issues rather than the things your team actually gets wrong.

## Common questions from developers

**"It's slow."** A normal change is a few seconds. If it is not, look at
`concurrency` and whether someone is pushing a 5,000-line diff. Large refactors are
genuinely slower; `max_diff_bytes` caps the worst case.

**"It flagged something wrong."** Expected sometimes. Push with `--no-verify` and
tell you — then fix it in `custom_rules` or `prompts.py`. Every false positive is a
bug in the config, not a reason to distrust the tool.

**"Do I need this if CI already runs linters?"** Yes — they do different jobs. The
linter checks form; this checks whether the logic is wrong and whether the query
can be injected. The prompt explicitly refuses to comment on formatting.

**"Does this replace human review?"** No. It clears the floor so the human review
is about design and product intent instead of "you forgot to handle null here."

## Troubleshooting

| Symptom | Fix |
|---|---|
| Hook does not run | `aicr doctor` — check the hook line; ensure `.git/hooks/pre-push` is executable |
| Works in terminal, not in a GUI git client | GUI apps do not load your shell profile. The installed hook uses an absolute path to `aicr`; if you moved the install, rerun `aicr install-hook` |
| `ANTHROPIC_API_KEY is not set` | Add the export to `~/.zshrc` (or `~/.bashrc`) and open a new terminal |
| Another pre-push hook already exists | `aicr install-hook --force` backs it up, or chain both from a wrapper script |
| Reviews are too noisy | Raise `fail_on`, tighten `custom_rules`, or add to `exclude` |
| Costs higher than expected | Check nobody is running `aicr repo` in a loop; lower `max_diff_bytes`; confirm `cache = true` |
