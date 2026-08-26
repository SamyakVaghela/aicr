"""Thin wrapper over the git CLI: figuring out what is about to be pushed."""

from __future__ import annotations

import fnmatch
import os
import re
import subprocess
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

ZERO = "0" * 40
NULL_SHAS = {ZERO, "0" * 64}


class GitError(RuntimeError):
    pass


def git(*args: str, cwd: Optional[Path] = None, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        errors="replace",
    )
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def repo_root(start: Optional[Path] = None) -> Path:
    try:
        out = git("rev-parse", "--show-toplevel", cwd=start or Path.cwd())
    except GitError as exc:
        raise GitError("Not inside a git repository.") from exc
    return Path(out.strip())


def current_branch(root: Path) -> str:
    return git("rev-parse", "--abbrev-ref", "HEAD", cwd=root).strip()


def user_identity(root: Path) -> str:
    """Best-effort developer identity for telemetry: git user.email, else user.name."""
    email = git("config", "user.email", cwd=root, check=False).strip()
    if email:
        return email
    name = git("config", "user.name", cwd=root, check=False).strip()
    return name or "unknown"


def user_name(root: Path) -> str:
    """`git config user.name`, separate from user_identity's email-first pick —
    for display contexts that want a human name alongside (or instead of) the
    email, e.g. a telemetry dashboard."""
    return git("config", "user.name", cwd=root, check=False).strip()


def remote_url(root: Path, remote: str = "origin") -> Optional[str]:
    out = git("config", "--get", f"remote.{remote}.url", cwd=root, check=False).strip()
    return out or None


_GITHUB_REMOTE_RE = re.compile(
    r"^(?:https?://(?:[^@/]+@)?github\.com/|git@github\.com:|ssh://git@github\.com/)"
    r"(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"
)


def parse_github_remote(url: Optional[str]) -> Optional[Tuple[str, str]]:
    """(owner, repo) from a GitHub remote URL (https or ssh form), else None —
    including for GitHub Enterprise-style or non-GitHub remotes, which this
    intentionally does not try to guess at."""
    if not url:
        return None
    m = _GITHUB_REMOTE_RE.match(url.strip())
    return (m.group("owner"), m.group("repo")) if m else None


def git_dir(root: Path) -> Path:
    out = git("rev-parse", "--absolute-git-dir", cwd=root).strip()
    return Path(out)


def default_branch(root: Path) -> str:
    """Best-effort guess at the integration branch."""
    for ref in ("refs/remotes/origin/HEAD",):
        out = git("symbolic-ref", "--quiet", ref, cwd=root, check=False).strip()
        if out:
            return out.rsplit("/", 1)[-1]
    for name in ("main", "master", "develop"):
        if git("rev-parse", "--verify", "--quiet", f"origin/{name}", cwd=root, check=False).strip():
            return name
    for name in ("main", "master"):
        if git("rev-parse", "--verify", "--quiet", name, cwd=root, check=False).strip():
            return name
    return "main"


def rev_exists(root: Path, rev: str) -> bool:
    return bool(git("rev-parse", "--verify", "--quiet", rev, cwd=root, check=False).strip())


def merge_base(root: Path, a: str, b: str) -> Optional[str]:
    out = git("merge-base", a, b, cwd=root, check=False).strip()
    return out or None


def changed_files(root: Path, rev_range: str) -> List[str]:
    out = git("diff", "--name-only", "--diff-filter=ACMR", rev_range, cwd=root, check=False)
    return [ln for ln in out.splitlines() if ln.strip()]


def diff_text(root: Path, rev_range: str, context: int = 5, paths: Optional[Sequence[str]] = None) -> str:
    args = [
        "diff", f"--unified={context}", "--no-color", "--diff-filter=ACMR",
        "--find-renames", rev_range,
    ]
    if paths:
        args += ["--", *paths]
    return git(*args, cwd=root, check=False)


def staged_diff(root: Path, context: int = 5) -> str:
    return git("diff", "--cached", f"--unified={context}", "--no-color",
               "--diff-filter=ACMR", cwd=root, check=False)


def worktree_diff(root: Path, context: int = 5) -> str:
    return git("diff", "HEAD", f"--unified={context}", "--no-color",
               "--diff-filter=ACMR", cwd=root, check=False)


def tracked_files(root: Path) -> List[str]:
    out = git("ls-files", cwd=root, check=False)
    return [ln for ln in out.splitlines() if ln.strip()]


def read_blob(root: Path, rev: str, path: str) -> str:
    return git("show", f"{rev}:{path}", cwd=root, check=False)


def resolve_push_range(root: Path, local_sha: str, remote_sha: str) -> Optional[str]:
    """Given one pre-push stdin line, return the rev range to review."""
    if local_sha in NULL_SHAS:
        return None  # branch deletion
    if remote_sha not in NULL_SHAS and rev_exists(root, remote_sha):
        return f"{remote_sha}..{local_sha}"

    # New branch (or the remote sha is unknown locally): compare against the
    # closest thing already published so we only review this branch's work.
    base = default_branch(root)
    for candidate in (f"origin/{base}", base):
        if rev_exists(root, candidate):
            mb = merge_base(root, candidate, local_sha)
            if mb and mb != local_sha:
                return f"{mb}..{local_sha}"
            if mb == local_sha:
                return None  # nothing new relative to base
    # Fall back to the last commit only, to avoid reviewing all of history.
    return f"{local_sha}~1..{local_sha}" if rev_exists(root, f"{local_sha}~1") else None


def read_prepush_stdin(stream) -> List[Tuple[str, str, str, str]]:
    """Parse `<local_ref> <local_sha> <remote_ref> <remote_sha>` lines."""
    rows = []
    for line in stream:
        parts = line.split()
        if len(parts) == 4:
            rows.append((parts[0], parts[1], parts[2], parts[3]))
    return rows


def upstream_range(root: Path) -> Optional[str]:
    """What `git push` would send on the current branch, for manual runs."""
    up = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}",
             cwd=root, check=False).strip()
    if up and rev_exists(root, up):
        rng = f"{up}..HEAD"
        if git("rev-list", "--count", rng, cwd=root, check=False).strip() not in ("", "0"):
            return rng
        return None
    base = default_branch(root)
    for candidate in (f"origin/{base}", base):
        if rev_exists(root, candidate):
            mb = merge_base(root, candidate, "HEAD")
            if mb and mb != git("rev-parse", "HEAD", cwd=root).strip():
                return f"{mb}..HEAD"
    return None


def is_excluded(path: str, patterns: Sequence[str]) -> bool:
    p = path.replace(os.sep, "/")
    for pat in patterns:
        if fnmatch.fnmatch(p, pat) or fnmatch.fnmatch(Path(p).name, pat):
            return True
        if pat.endswith("/*") and p.startswith(pat[:-1]):
            return True
        if f"/{pat.rstrip('/*')}/" in f"/{p}":
            # matches directory patterns like node_modules/* anywhere in the tree
            if pat.endswith("/*"):
                return True
    return False
