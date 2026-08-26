# Smoke test samples

Ten files with known-correct verdicts, used to check that a provider/model
combination actually reviews well before you roll it out to the team.

```bash
python3 samples/run-smoke.py                    # use the configured provider
python3 samples/run-smoke.py --provider gemini  # try a specific one
python3 samples/run-smoke.py -v                 # list every finding
```

The runner copies the samples into a throwaway git repo in `/tmp`, reviews each
file on its own, and compares the verdict against what it should be. Exit code
`0` if everything matched. Nothing is pushed and your own repo is untouched.

## What's here

**4 files that must be BLOCKED** — each one plants distinct, realistic bugs:

| File | Plants |
|---|---|
| `bad_01_payments.py` | Hardcoded Stripe key, SQL injection (two ways), bare `except` that reports success on failure |
| `bad_02_auth.js` | `eval()` on a query param, timing-unsafe token compare, MD5 password hashing, password written to logs, unawaited promise |
| `bad_03_orders.py` | N+1 query, unbounded `.all()`, check-then-act race on stock, HTTP call with no timeout |
| `bad_04_provision.sh` | Command injection via `eval`, unquoted `$VAR` into `rm -rf`, DB password in argv, no `set -euo pipefail` |

**6 files that must PASS** — the clean counterparts, in Python, JavaScript,
Bash, Go, and TypeScript.

## The good files are the real test

Any model flags `eval()`. Catching the bad files tells you almost nothing.

What decides whether your team keeps this tool switched on is the `good_*`
column. Those files are deliberately written to bait a trigger-happy reviewer:
`good_01` has a raw SQL string (parameterized), `good_02` does a crypto
comparison (constant-time), `good_04` calls `rm`-adjacent operations (guarded
and validated), `good_05` shares mutable state across goroutines (mutex-held).
A reviewer that flags those is one your developers will start bypassing within
a week.

**A false positive on a `good_` file is a worse result than a miss on a
`bad_` file.** Tune for that.

## Reading the results

| Result | What it means | What to do |
|---|---|---|
| All 10 ✓ | Model is well-calibrated for your stack | Ship it |
| `good_` blocked | False positives — too aggressive | Tighten the HARD RULES in `prompts.py`, or add a clarifying `custom_rules` entry |
| `bad_03` missed | Model catches syntax-level bugs but not semantic ones | Expected on small models. Move up a tier (Flash-Lite → Flash) |
| Several `bad_` missed | Model is too weak for review work | Change model before changing anything else |

`bad_03` is the honest difficulty gauge. Hardcoded secrets and `eval()` are
pattern matching; an N+1 query and a check-then-act race need the model to
actually reason about the code. The `mock` provider fails exactly this one file,
which is the expected result and a good check that the harness discriminates.

## Config

`samples/.aicr.toml` is a filled-in example config — a realistic
`project_context` and nine `custom_rules`. It gets copied into the scratch repo,
so the samples are reviewed the way a real project would be. Worth reading as a
template for your own `.aicr.toml`.

## A note on the bad files

They contain real vulnerability patterns. They are inert (no real credentials,
never imported, not wired to anything), but:

- Secret scanners may flag `bad_01`/`bad_04`. The strings are fake.
- If you run `aicr repo` on this project, these files will light up. That is
  correct behaviour, not a bug.
- Don't copy from them. Every one has a `good_` counterpart showing the fix.
