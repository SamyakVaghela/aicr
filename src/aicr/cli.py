"""aicr command line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from . import __version__, cursorinit, ghinit, gitutil, hookinstall, telemetry
from .config import DEFAULT_TEAM_CONFIG, Config, load_config, user_config_path
from .engine import Reviewer
from .models import ReviewResult, SEVERITY_ORDER, severity_rank
from .providers import ConfigError, ProviderError, available, get_provider
from .report import render_markdown, render_terminal

EXIT_OK = 0
EXIT_BLOCKED = 1
EXIT_ERROR = 2

# Last review produced in this process, so the pre-push path can write a report
# file after the verdict without re-running anything.
_LAST_RESULT: dict = {}


def _eprint(msg: str = "") -> None:
    print(msg, file=sys.stderr)


def _load(args) -> tuple:
    root = gitutil.repo_root(Path(args.repo) if getattr(args, "repo", None) else None)
    cfg = load_config(root)
    if getattr(args, "provider", None):
        cfg.data["provider"] = args.provider
    if getattr(args, "model", None):
        cfg.data["_model_override"] = args.model
    if getattr(args, "fail_on", None):
        cfg.data["fail_on"] = args.fail_on
    if getattr(args, "no_cache", False):
        cfg.data["cache"] = False
    return root, cfg


def _emit(result: ReviewResult, cfg: Config, args) -> None:
    fail_on = str(cfg.get("fail_on", "high"))
    fmt = getattr(args, "format", "terminal")

    if fmt == "json":
        payload = result.to_dict()
        payload["fail_on"] = fail_on
        payload["blocked"] = bool(result.blocking(fail_on))
        print(json.dumps(payload, indent=2))
    elif fmt == "markdown":
        print(render_markdown(result, fail_on))
    else:
        _eprint(render_terminal(result, fail_on, stream=sys.stderr))

    out = getattr(args, "out", None)
    if out:
        p = Path(out)
        p.parent.mkdir(parents=True, exist_ok=True)
        text = (json.dumps(result.to_dict(), indent=2) if p.suffix == ".json"
                else render_markdown(result, fail_on))
        p.write_text(text, encoding="utf-8")
        _eprint(f"aicr: report written to {p}")


def _verdict(result: ReviewResult, cfg: Config) -> int:
    fail_on = str(cfg.get("fail_on", "high"))
    if result.errors and not result.findings and not bool(cfg.get("fail_open", True)):
        return EXIT_ERROR
    return EXIT_BLOCKED if result.blocking(fail_on) else EXIT_OK


def _progress(total_label: str):
    def cb(done: int, total: int):
        if total > 1 and sys.stderr.isatty():
            print(f"\raicr: reviewing {total_label} … {done}/{total} batches",
                  end="", file=sys.stderr, flush=True)
            if done == total:
                print("\r" + " " * 60 + "\r", end="", file=sys.stderr, flush=True)
    return cb


def _handle_provider_failure(exc: Exception, cfg: Config) -> int:
    fail_open = bool(cfg.get("fail_open", True))
    kind = "configuration" if isinstance(exc, ConfigError) else "provider"
    _eprint("")
    _eprint(f"aicr: {kind} error — {exc}")
    if fail_open and not isinstance(exc, ConfigError):
        _eprint("aicr: fail_open is on, so the push is allowed. Review manually.")
        return EXIT_OK
    if fail_open and isinstance(exc, ConfigError):
        _eprint("aicr: fix the configuration above, then push again.")
        _eprint("aicr: to push without review right now: git push --no-verify")
        return EXIT_ERROR
    return EXIT_ERROR


def _fail(exc: Exception, cfg: Config, root: Path, source: str, branch: str) -> int:
    """Handle a ProviderError/ConfigError and record it for admin visibility.

    A misconfigured reviewer is exactly the case CLAUDE.md calls out as worse
    than no reviewer at all, so it gets logged the same as a real review does.
    """
    code = _handle_provider_failure(exc, cfg)
    telemetry.record(cfg, telemetry.build_event(
        cfg, root, source, branch, blocked=(code != EXIT_OK), error=str(exc),
    ))
    return code


# --------------------------------------------------------------------------- commands

def cmd_init(args) -> int:
    root = gitutil.repo_root(Path(args.repo) if args.repo else None)
    target = root / ".aicr.toml"
    if target.exists() and not args.force:
        _eprint(f"aicr: {target} already exists (use --force to overwrite)")
        return EXIT_ERROR
    target.write_text(DEFAULT_TEAM_CONFIG, encoding="utf-8")
    print(f"Wrote {target}")

    gi = root / ".gitignore"
    existing = gi.read_text(encoding="utf-8") if gi.exists() else ""
    missing = [ln for ln in (".aicr.local.toml", ".aicr-review.md")
               if ln not in existing]
    if missing:
        with gi.open("a", encoding="utf-8") as fh:
            fh.write(("" if existing.endswith("\n") or not existing else "\n")
                     + "\n# aicr: per-developer overrides and local review reports\n"
                     + "\n".join(missing) + "\n")
        print(f"Added {', '.join(missing)} to .gitignore")

    print("\nNext: edit .aicr.toml (project_context + custom_rules), commit it,")
    print("then every developer runs:  aicr install-hook")
    return EXIT_OK


def cmd_install_hook(args) -> int:
    root = gitutil.repo_root(Path(args.repo) if args.repo else None)

    if args.shared:
        path, action = hookinstall.install_shared(root, force=args.force)
        if action == "EXISTING_HOOK":
            _eprint(f"aicr: a pre-push hook already exists at {path}.")
            _eprint("aicr: rerun with --force to back it up and replace it.")
            return EXIT_ERROR
        print(f"pre-push hook {action}: {path}  (core.hooksPath -> {path.parent.name})")
        print(f"Every `git push` from this clone now runs the AI review first.\n")
        print(f"Commit {path.parent}/ so the rest of the team gets the hook script itself.")
        print("Everyone else then needs exactly one command per clone (git can't skip")
        print("this — see CLAUDE.md for why), instead of installing aicr's hook by hand:")
        print(f"\n    git config core.hooksPath {path.parent.name}\n")
        print("That does require `aicr` already on their PATH (pipx/pip install) — this")
        print("mode trades away the absolute-path fallback the default install gives GUI")
        print("git clients (Tower, GitHub Desktop), since the script is now shared verbatim")
        print("across everyone's machines rather than tailored to just yours.")
        return EXIT_OK

    path, action = hookinstall.install(root, force=args.force)
    if action == "EXISTING_HOOK":
        _eprint(f"aicr: a pre-push hook already exists at {path}.")
        _eprint("aicr: rerun with --force to back it up and replace it.")
        return EXIT_ERROR
    print(f"pre-push hook {action}: {path}")
    print("Every `git push` from this clone now runs the AI review first.")
    return EXIT_OK


def cmd_uninstall_hook(args) -> int:
    root = gitutil.repo_root(Path(args.repo) if args.repo else None)
    print(hookinstall.uninstall(root))
    return EXIT_OK


def cmd_cursor_init(args) -> int:
    """Install the Cursor IDE integration (agent push gate + slash commands)."""
    root = gitutil.repo_root(Path(args.repo) if args.repo else None)
    if args.uninstall:
        for line in cursorinit.uninstall(root):
            print(line)
        return EXIT_OK
    for line in cursorinit.install(root, force=args.force):
        print(line)
    print("\nCommit .cursor/ so the whole team gets it.")
    print("In Cursor: /aicr-review and /aicr-fix are now available in chat,")
    print("and the agent cannot `git push` past a blocking finding.")
    return EXIT_OK


def cmd_github_init(args) -> int:
    """Install the GitHub Actions integration (PR-comment reviews)."""
    root = gitutil.repo_root(Path(args.repo) if args.repo else None)
    if args.uninstall:
        for line in ghinit.uninstall(root):
            print(line)
        return EXIT_OK
    for line in ghinit.install(root, force=args.force):
        print(line)
    print("\nEdit the 'Install aicr' step to point at wherever your org hosts aicr,")
    print("then commit .github/workflows/ so every PR gets a review comment.")
    return EXIT_OK


def cmd_cursor_hook(args) -> int:
    """Cursor `beforeShellExecution` hook.

    Reads Cursor's JSON on stdin, writes a permission decision to stdout.
    Must ALWAYS print valid JSON and exit 0 — anything else and Cursor either
    blocks every shell command or ignores us entirely.
    """
    def emit(permission: str, user_msg: str = "", agent_msg: str = "") -> int:
        out = {"permission": permission}
        if user_msg:
            out["user_message"] = user_msg
        if agent_msg:
            out["agent_message"] = agent_msg
        print(json.dumps(out))
        return EXIT_OK

    try:
        raw = sys.stdin.read()
        hook_input = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        return emit("allow")

    try:
        is_push, cwd = cursorinit.decide(hook_input)
        if not is_push:
            return emit("allow")

        root = gitutil.repo_root(Path(cwd) if cwd else None)
        cfg = load_config(root)
        rng = gitutil.upstream_range(root)
        if not rng:
            return emit("allow")

        diff = gitutil.diff_text(root, rng, context=int(cfg.get("context_lines") or 5))
        rv = Reviewer(cfg, root)
        files, _ = rv.files_from_diff(diff)
        if not files:
            return emit("allow")

        result = rv.review(files, branch=gitutil.current_branch(root),
                           commit_messages=_commit_messages(root, rng))
    except (ProviderError, ConfigError) as exc:
        # Never wedge the agent on our own misconfiguration.
        return emit("allow", user_msg=f"aicr could not run ({exc}). Push not reviewed.")
    except Exception as exc:  # noqa: BLE001
        return emit("allow", user_msg=f"aicr error: {exc}. Push not reviewed.")

    fail_on = str(cfg.get("fail_on", "high"))
    blocking = result.blocking(fail_on)
    if not blocking:
        return emit("allow")

    report = render_markdown(result, fail_on, title="aicr blocked this push")
    lines = [f"- [{f.severity}] {f.file}"
             + (f":{f.line}" if f.line else "")
             + f" — {f.title}: {f.detail}"
             + (f" Suggested fix: {f.suggestion}" if f.suggestion else "")
             for f in result.sorted_findings() if f.rank >= severity_rank(fail_on)]
    return emit(
        "deny",
        user_msg=(f"aicr blocked this push — {len(blocking)} issue(s) at "
                  f"'{fail_on}' or above. See the findings in chat."),
        agent_msg=(
            f"The push was blocked by aicr, the team's pre-push code reviewer. "
            f"{len(blocking)} blocking finding(s) must be fixed before this can "
            f"be pushed:\n\n" + "\n".join(lines) +
            "\n\nFix these properly — change the code so the problem is gone. "
            "Do NOT retry with `git push --no-verify`, do not edit .aicr.toml to "
            "lower the severity threshold, and do not add files to `exclude` to "
            "silence a finding. If you believe one of these is a false positive, "
            "stop and tell the user instead of working around it. "
            "After fixing, commit and push again.\n\n" + report
        ),
    )


def cmd_doctor(args) -> int:
    try:
        root, cfg = _load(args)
    except gitutil.GitError as exc:
        _eprint(f"✗ {exc}")
        return EXIT_ERROR

    ok = True
    pc = cfg.provider_config()
    provider = None
    provider_err: Optional[Exception] = None
    try:
        provider = get_provider(cfg.provider, pc)
    except (ProviderError, ConfigError) as exc:
        provider_err = exc

    print(f"aicr {__version__}")
    print(f"  repo            {root}")
    print(f"  branch          {gitutil.current_branch(root)}")
    print(f"  config sources  {', '.join(cfg.sources) or '(defaults only)'}")
    print(f"  user config     {user_config_path()}")
    print(f"  provider        {cfg.provider}")
    print(f"  model           {getattr(provider, 'model', None) or pc.get('model') or 'unknown'}")
    print(f"  fail_on         {cfg.get('fail_on')}   (blocks push at this severity and above)")
    print(f"  fail_open       {cfg.get('fail_open')}")
    print(f"  hook            {hookinstall.status(root)}")
    tcfg = cfg.get("telemetry") or {}
    if bool(tcfg.get("enabled", False)) and str(tcfg.get("webhook_url") or "").strip():
        print(f"  telemetry       on -> {tcfg['webhook_url']}")
    else:
        print("  telemetry       off (local history only: " + str(telemetry.history_path()) + ")")

    rng = gitutil.upstream_range(root)
    print(f"  pending push    {rng or 'nothing to push'}")

    print("\n  provider check …", end=" ", flush=True)
    if provider_err is not None:
        ok = False
        print("FAILED")
        _eprint(f"    {provider_err}")
    else:
        try:
            print(provider.healthcheck())
        except (ProviderError, ConfigError) as exc:
            ok = False
            print("FAILED")
            _eprint(f"    {exc}")

    if getattr(args, "test_webhook", False):
        print("  webhook check   …", end=" ", flush=True)
        sent, detail = telemetry.send_test(cfg, root)
        if sent:
            print(f"OK ({detail})")
        else:
            ok = False
            print("FAILED")
            _eprint(f"    {detail}")

    print("\n" + ("All good." if ok else "Problems found — see above."))
    return EXIT_OK if ok else EXIT_ERROR


def cmd_review(args) -> int:
    try:
        root, cfg = _load(args)
    except gitutil.GitError as exc:
        _eprint(f"aicr: {exc}")
        return EXIT_ERROR

    context = int(cfg.get("context_lines") or 5)
    branch = gitutil.current_branch(root)
    commits: List[str] = []
    whole_files = False

    if args.files:
        try:
            rv = Reviewer(cfg, root)
        except (ProviderError, ConfigError) as exc:
            return _fail(exc, cfg, root, "review", branch)
        picked, skipped = rv.files_from_paths(list(args.files))
        if skipped and args.verbose:
            _eprint("aicr: skipped " + ", ".join(skipped))
        if not picked:
            _eprint("aicr: none of those files are reviewable.")
            return EXIT_OK
        return _run_review_with(rv, cfg, args, picked, True, branch, commits, source="review")

    if args.staged:
        diff = gitutil.staged_diff(root, context)
        label = "staged changes"
    elif args.working:
        diff = gitutil.worktree_diff(root, context)
        label = "uncommitted changes"
    elif args.range:
        diff = gitutil.diff_text(root, args.range, context=context)
        label = args.range
        commits = _commit_messages(root, args.range)
    else:
        rng = gitutil.upstream_range(root)
        if not rng:
            _eprint("aicr: nothing to review — this branch has no unpushed commits.")
            _eprint("aicr: try `aicr review --staged`, `--working`, or `--range A..B`.")
            return EXIT_OK
        diff = gitutil.diff_text(root, rng, context=context)
        label = rng
        commits = _commit_messages(root, rng)

    if not diff.strip():
        _eprint(f"aicr: no changes found in {label}.")
        return EXIT_OK

    try:
        rv = Reviewer(cfg, root)
    except (ProviderError, ConfigError) as exc:
        return _fail(exc, cfg, root, "review", branch)
    files, skipped = rv.files_from_diff(diff)
    if skipped and args.verbose:
        _eprint("aicr: skipped " + ", ".join(skipped))
    if not files:
        _eprint("aicr: no reviewable files (everything was excluded or binary).")
        return EXIT_OK
    return _run_review_with(rv, cfg, args, files, whole_files, branch, commits, source="review")


def _run_review_with(rv: Reviewer, cfg: Config, args, files, whole_files, branch, commits,
                      source: str = "review") -> int:
    try:
        result = rv.review(files, whole_files=whole_files, branch=branch,
                           commit_messages=commits, progress=_progress(branch))
    except (ProviderError, ConfigError) as exc:
        return _fail(exc, cfg, rv.root, source, branch)
    _LAST_RESULT["result"] = result
    _emit(result, cfg, args)
    code = _verdict(result, cfg)
    telemetry.record(cfg, telemetry.build_event(
        cfg, rv.root, source, branch, blocked=(code == EXIT_BLOCKED), result=result,
    ))
    return code


def _commit_messages(root: Path, rng: str) -> List[str]:
    out = gitutil.git("log", "--pretty=%s", rng, cwd=root, check=False)
    return [ln.strip() for ln in out.splitlines() if ln.strip()][:20]


def cmd_repo(args) -> int:
    try:
        root, cfg = _load(args)
    except gitutil.GitError as exc:
        _eprint(f"aicr: {exc}")
        return EXIT_ERROR

    paths = gitutil.tracked_files(root)
    if args.path:
        wanted = [p.rstrip("/") for p in args.path]
        paths = [p for p in paths if any(p == w or p.startswith(w + "/") for w in wanted)]
    if not paths:
        _eprint("aicr: no tracked files matched.")
        return EXIT_OK

    branch = gitutil.current_branch(root)
    try:
        rv = Reviewer(cfg, root)
    except (ProviderError, ConfigError) as exc:
        return _fail(exc, cfg, root, "repo", branch)
    files, skipped = rv.files_from_paths(paths)
    if args.verbose and skipped:
        _eprint(f"aicr: skipped {len(skipped)} file(s)")
    if not files:
        _eprint("aicr: nothing reviewable.")
        return EXIT_OK
    _eprint(f"aicr: full-repo review of {len(files)} file(s) — this may take a while "
            f"and will use a fair number of tokens.")
    return _run_review_with(rv, cfg, args, files, True, branch, [], source="repo")


def cmd_pre_push(args) -> int:
    """Hook entry point. Reads pre-push stdin lines."""
    try:
        root, cfg = _load(args)
    except gitutil.GitError as exc:
        _eprint(f"aicr: {exc}")
        return EXIT_OK  # never block a push because we cannot find the repo

    rows = gitutil.read_prepush_stdin(sys.stdin) if not sys.stdin.isatty() else []
    ranges: List[str] = []
    for _local_ref, local_sha, _remote_ref, remote_sha in rows:
        rng = gitutil.resolve_push_range(root, local_sha, remote_sha)
        if rng:
            ranges.append(rng)
    if not rows:
        rng = gitutil.upstream_range(root)
        if rng:
            ranges.append(rng)

    if not ranges:
        _eprint("aicr: nothing new to review.")
        return EXIT_OK

    context = int(cfg.get("context_lines") or 5)
    diffs, commits = [], []
    for rng in ranges:
        diffs.append(gitutil.diff_text(root, rng, context=context))
        commits += _commit_messages(root, rng)
    diff = "\n".join(d for d in diffs if d.strip())

    if not diff.strip():
        _eprint("aicr: no reviewable code changes in this push.")
        return EXIT_OK

    branch = gitutil.current_branch(root)
    try:
        rv = Reviewer(cfg, root)
    except (ProviderError, ConfigError) as exc:
        return _fail(exc, cfg, root, "pre_push", branch)

    files, skipped = rv.files_from_diff(diff)
    if not files:
        _eprint("aicr: only excluded or binary files in this push — nothing to review.")
        return EXIT_OK

    _eprint(f"aicr: reviewing {len(files)} changed file(s) before push …")
    args.format = "terminal"
    code = _run_review_with(rv, cfg, args, files, False, branch, commits, source="pre_push")
    if code == EXIT_BLOCKED:
        # GUI git clients (Cursor/VS Code Source Control, Tower, GitHub Desktop)
        # swallow hook stderr into a log channel nobody reads. Leave the report
        # somewhere the developer can actually open.
        _write_report_file(root, cfg)
    return code


def _write_report_file(root: Path, cfg: Config) -> None:
    result = _LAST_RESULT.get("result")
    if result is None:
        return
    name = str(cfg.get("report_path") or ".aicr-review.md")
    try:
        path = root / name
        path.write_text(
            render_markdown(result, str(cfg.get("fail_on", "high")),
                            title="aicr blocked this push"),
            encoding="utf-8",
        )
        _eprint(f"aicr: full report written to {path}")
    except OSError:
        pass


# --------------------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aicr",
        description="AI code review that runs on your machine and gates git push.",
    )
    p.add_argument("--version", action="version", version=f"aicr {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp, with_output=True):
        sp.add_argument("--repo", help="path inside the git repo (default: cwd)")
        sp.add_argument("--provider", choices=available(), help="override configured provider")
        sp.add_argument("--model", help="override the model name")
        sp.add_argument("--fail-on", choices=SEVERITY_ORDER, dest="fail_on",
                        help="severity that blocks the push")
        sp.add_argument("--no-cache", action="store_true", help="ignore cached reviews")
        sp.add_argument("-v", "--verbose", action="store_true")
        if with_output:
            sp.add_argument("--format", choices=["terminal", "markdown", "json"],
                            default="terminal")
            sp.add_argument("--out", help="also write the report to this file (.md or .json)")

    sp = sub.add_parser("init", help="create .aicr.toml in this repo")
    sp.add_argument("--repo")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("install-hook", help="install the blocking pre-push hook")
    sp.add_argument("--repo")
    sp.add_argument("--force", action="store_true", help="replace an existing pre-push hook")
    sp.add_argument("--shared", action="store_true",
                    help="write to .githooks/ (commit it) instead of .git/hooks/, "
                         "and point this clone's core.hooksPath at it")
    sp.set_defaults(func=cmd_install_hook)

    sp = sub.add_parser("uninstall-hook", help="remove the pre-push hook")
    sp.add_argument("--repo")
    sp.set_defaults(func=cmd_uninstall_hook)

    sp = sub.add_parser("cursor-init",
                        help="install the Cursor IDE integration (agent gate + /commands)")
    sp.add_argument("--repo")
    sp.add_argument("--force", action="store_true", help="overwrite existing aicr files")
    sp.add_argument("--uninstall", action="store_true")
    sp.set_defaults(func=cmd_cursor_init)

    sp = sub.add_parser("cursor-hook",
                        help="Cursor beforeShellExecution hook (reads JSON on stdin)")
    sp.add_argument("--repo")
    sp.set_defaults(func=cmd_cursor_hook)

    sp = sub.add_parser("github-init",
                        help="install the GitHub Actions integration (PR-comment reviews)")
    sp.add_argument("--repo")
    sp.add_argument("--force", action="store_true", help="overwrite an existing workflow file")
    sp.add_argument("--uninstall", action="store_true")
    sp.set_defaults(func=cmd_github_init)

    sp = sub.add_parser("doctor", help="check config, hook, and provider connectivity")
    common(sp, with_output=False)
    sp.add_argument("--test-webhook", action="store_true",
                    help="send one test event to telemetry.webhook_url and report the result")
    sp.set_defaults(func=cmd_doctor, format="terminal", out=None)

    sp = sub.add_parser("review", help="review changes (default: what you are about to push)")
    common(sp)
    g = sp.add_mutually_exclusive_group()
    g.add_argument("--staged", action="store_true", help="review staged changes")
    g.add_argument("--working", action="store_true", help="review uncommitted changes")
    g.add_argument("--range", help="review a git range, e.g. main..HEAD")
    g.add_argument("--files", nargs="+", help="review these files in full")
    sp.set_defaults(func=cmd_review)

    sp = sub.add_parser("repo", help="review the whole tracked repository")
    common(sp)
    sp.add_argument("--path", nargs="+", help="limit to these directories or files")
    sp.set_defaults(func=cmd_repo)

    sp = sub.add_parser("pre-push", help="hook entry point (reads pre-push stdin)")
    common(sp, with_output=False)
    sp.add_argument("remote", nargs="?")
    sp.add_argument("url", nargs="?")
    sp.set_defaults(func=cmd_pre_push, format="terminal", out=None)

    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        _eprint("\naicr: interrupted.")
        return EXIT_ERROR
    except gitutil.GitError as exc:
        _eprint(f"aicr: {exc}")
        return EXIT_ERROR
    except RuntimeError as exc:
        _eprint(f"aicr: {exc}")
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
