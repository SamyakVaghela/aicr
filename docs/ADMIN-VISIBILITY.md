# Review visibility for managers

A short explainer for why/how we can see whether the team is using `aicr`,
the AI code-review gate that runs before every `git push`.

## The ask

`aicr` blocks a developer's push if the AI reviewer finds a critical or
high-severity issue (secrets, SQL injection, etc.). It runs entirely on each
developer's laptop. The open question: **can a manager see that it's actually
being used, and what it's catching?**

## What we built

Two pieces, covering two different questions.

**1. A Teams feed, for "is the team using this."** Every time a review runs,
it sends one small event to a Teams channel:

```
alice@company.com  ·  payments-api/main  ·  BLOCKED  ·  1 critical
bob@company.com    ·  payments-api/main  ·  clean
```

Just the essentials — who, which repo/branch, pass or blocked, and a count of
issues by severity. No source code and no finding details are sent unless we
explicitly turn that on. Each developer's `aicr` install posts directly to a
Teams webhook URL — no new server to run.

**2. A comment on the pull request itself, for "read the findings next to the
code."** A GitHub Actions workflow reviews every PR when it's opened or
updated and posts the full findings as a PR comment — visible to anyone who
can see the PR, whether or not they have `aicr` installed. It updates the same
comment on each new push rather than piling up duplicates.

## What this gives you

- A live feed of review activity across the team, in the channel of your choice.
- A rough read on adoption: if a name never shows up, that's worth a
  conversation.
- The actual findings sitting on the PR, for anyone reviewing the code —
  including you, without installing anything.
- Zero added friction for developers — both ride along with a review that was
  already going to run.

## The one honest limit

A developer can type `git push --no-verify` to skip the **local** review
entirely. When that happens, the local tool never runs, so **the Teams feed**
has nothing to report — a missing entry could mean "didn't push" or "pushed
around the gate," and there's no way to tell them apart from the developer's
machine alone.

**The GitHub Actions comment doesn't have that blind spot** — it runs on
GitHub's servers whenever a PR gets a push, regardless of what happened
locally. Its gap is different: it only fires if a PR was opened at all (a
direct push to a protected branch skips it), and by default it only comments —
it does not block merging, so a reviewer still has to look.

So: treat both as **visibility**, not a **compliance audit**. Together they
answer "is the team using this, and what is it finding" — not "did every
single push get reviewed," which needs the stronger step below.

## If you need the stronger guarantee later

Real, unavoidable enforcement means a check on the git host itself (GitHub/
GitLab required status checks / branch protection) instead of on the
developer's machine — a check nobody can opt out of locally. That's a
deliberate next step, not something we've built yet, and it reuses the same
`aicr` tool under the hood.

## Setup effort

Both are one-time, nothing ongoing to maintain:

- **Teams feed:** someone with Teams admin rights creates a channel
  **Workflow** ("Post to a channel when a webhook request is received") and
  hands us the URL. One line in the shared project config after that —
  nothing per developer. Run `aicr doctor --test-webhook` right after pasting
  the URL in — it sends one throwaway test event and confirms it actually
  landed in the channel, so we know the connection works before relying on it
  for a real push.
- **PR comment:** we commit one workflow file to the repo (`aicr github-init`).
  Nothing for developers to install; it just runs.
